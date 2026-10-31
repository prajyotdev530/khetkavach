"""Crop health from Sentinel-2 optical images via Microsoft Planetary Computer (F2, feeds F12 overlays).

Reads only the 500 m box around the farm (cloud-optimised range reads, never whole scenes), masks clouds with
the scene classification layer (SCL), and reports NDVI (greenness) and NDMI (crop moisture) now and in the same
weeks last year. If no recent scene shows the box clearly, it raises TooCloudy so the agent can switch to radar.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import odc.stac
import planetary_computer
import pystac
import pystac_client

from app import cache
from app.config import get_settings
from app.engine import overlay
from app.models import OpticalResult, Overlay, SourceRef, Stat
from app.sources.common import NotFarmland, SourceUnavailable, TooCloudy, bounds_to_bbox, now_ist

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
SOURCE = "Sentinel-2 L2A (Planetary Computer)"
SOURCE_URL = "https://planetarycomputer.microsoft.com/dataset/sentinel-2-l2a"
BANDS = ["B02", "B03", "B04", "B08", "B11", "SCL"]
SCL_CLEAR = (4, 5, 7)          # vegetation, not vegetated, unclassified
SCL_WATER = 6
SCL_CLOUD = (3, 8, 9, 10)      # cloud shadow, cloud medium/high probability, thin cirrus
MIN_CLEAR = 0.6
MAX_SCENE_CLOUD = 80
RES_DEG = 0.00009              # ≈10 m pixels on a lat/lon grid, so overlays align exactly with the map
BOA_OFFSET = 1000.0            # verified: ESA product metadata BOA_ADD_OFFSET = -1000 for baseline >= 04.00
QUANTIFICATION = 10000.0

log = logging.getLogger("khetkavach.optical")
# Cloud-friendly GDAL settings, plus a per-request timeout and retries so one stalled blob read fails fast and is
# retried inside the 25 s satellite budget instead of using it all up.
odc.stac.configure_rio(cloud_defaults=True, GDAL_HTTP_TIMEOUT=15, GDAL_HTTP_CONNECTTIMEOUT=5,
                       GDAL_HTTP_MAX_RETRY=2, GDAL_HTTP_RETRY_DELAY=0.5)
_catalog_lock = threading.Lock()
_catalog: Optional[pystac_client.Client] = None
_scl_memo: dict[str, "SclStats"] = {}


@dataclass
class SclStats:
    """How much of the farm box one scene shows clearly, as water, or as cloud."""

    clear: float
    water: float
    cloud: float


def catalog() -> pystac_client.Client:
    """Open the Planetary Computer STAC API once; items are signed so their files can be read anonymously."""
    global _catalog
    with _catalog_lock:
        if _catalog is None:
            _catalog = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
        return _catalog


def search(bbox: list[float], start: date, end: date, limit: int) -> list[pystac.Item]:
    """Sentinel-2 scenes covering the box between two dates with scene cloud < 80%, newest first."""
    items = catalog().search(
        collections=[COLLECTION], bbox=bbox, datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": MAX_SCENE_CLOUD}},
        sortby=[{"field": "properties.datetime", "direction": "desc"}], max_items=limit,
    ).items()
    return list(items)


def load(item: pystac.Item, bbox: list[float], bands: list[str]):
    """Read just the box for the given bands of one scene onto a ~10 m lat/lon grid."""
    ds = odc.stac.load([item], bands=bands, bbox=bbox, crs="EPSG:4326", resolution=RES_DEG,
                       resampling={"B11": "bilinear", "*": "nearest"}, pool=len(bands))
    return ds.isel(time=0)


def scl_stats(item: pystac.Item, bbox: list[float]) -> SclStats:
    """Load only the SCL band and measure clear / water / cloud fractions of the box (memoised per scene)."""
    key = f"{item.id}:{','.join(f'{v:.5f}' for v in bbox)}"
    if key not in _scl_memo:
        scl = load(item, bbox, ["SCL"])["SCL"].values
        total = scl.size or 1
        _scl_memo[key] = SclStats(
            clear=float(np.isin(scl, SCL_CLEAR).sum() / total),
            water=float((scl == SCL_WATER).sum() / total),
            cloud=float(np.isin(scl, SCL_CLOUD).sum() / total),
        )
    return _scl_memo[key]


def _scene_date(item: pystac.Item) -> date:
    """The acquisition date of a scene."""
    return datetime.fromisoformat(item.properties["datetime"].replace("Z", "+00:00")).date()


def _stats_for(items: list[pystac.Item], bbox: list[float]) -> list[tuple[pystac.Item, SclStats]]:
    """Measure SCL fractions for several scenes in parallel threads."""
    with ThreadPoolExecutor(max_workers=max(1, len(items))) as pool:
        stats = list(pool.map(lambda it: scl_stats(it, bbox), items))
    return list(zip(items, stats))


@dataclass
class SceneArrays:
    """Per-pixel reflectances, indices and the clear mask for one scene."""

    item: pystac.Item
    valid: np.ndarray
    ndvi: np.ndarray
    ndmi: np.ndarray
    rgb_dn: tuple[np.ndarray, np.ndarray, np.ndarray]
    bounds: list[list[float]]


class SceneUnusable(Exception):
    """A scene's pixels for the box are corrupt or could not be read; the next clear scene is tried instead."""


def read_scene(item: pystac.Item, bbox: list[float]) -> SceneArrays:
    """Load all bands for the box, remove the reflectance offset, and compute NDVI and NDMI per pixel.

    Raises SceneUnusable if the read fails or the values are implausible. (Seen live: a 2026-10-28 Punjab scene
    whose B04 file holds 0-255 values instead of L2A digital numbers, which are ≥ 1000 with the offset.)
    """
    try:
        ds = load(item, bbox, BANDS)
    except Exception as exc:  # truncated or failed blob reads surface as rasterio/GDAL errors
        raise SceneUnusable(f"{item.id}: read failed ({type(exc).__name__})") from exc
    baseline = float(item.properties.get("s2:processing_baseline") or 0)
    offset = BOA_OFFSET if baseline >= 4.0 else 0.0
    clear = np.isin(ds["SCL"].values, SCL_CLEAR)
    nir = ds["B08"].values[clear]
    if offset and (nir.size == 0 or float(np.nanmedian(nir)) < offset):
        raise SceneUnusable(f"{item.id}: implausible reflectance values (NIR median below the {offset:.0f} offset)")
    dn = {b: ds[b].values.astype("float64") - offset for b in BANDS if b != "SCL"}
    refl = {b: np.clip(v / QUANTIFICATION, 0.0, None) for b, v in dn.items()}
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (refl["B08"] - refl["B04"]) / (refl["B08"] + refl["B04"])
        ndmi = (refl["B08"] - refl["B11"]) / (refl["B08"] + refl["B11"])
    valid = clear & np.isfinite(ndvi) & np.isfinite(ndmi)
    if valid.sum() < max(20, 0.5 * clear.sum()):
        raise SceneUnusable(f"{item.id}: too few valid pixels ({int(valid.sum())})")
    bb = ds.odc.geobox.boundingbox
    return SceneArrays(item, valid, ndvi, ndmi, (dn["B04"], dn["B03"], dn["B02"]),
                       [[bb.bottom, bb.left], [bb.top, bb.right]])


def _stat(values: np.ndarray, valid: np.ndarray) -> Stat:
    """Median and 10th/90th percentiles over valid pixels, rounded to 3 decimals."""
    v = values[valid]
    return Stat(median=round(float(np.median(v)), 3), p10=round(float(np.percentile(v, 10)), 3),
                p90=round(float(np.percentile(v, 90)), 3))


def compute(lat: float, lon: float, bounds: list[list[float]], today: date, window_days: int) -> dict:
    """Run the whole optical pipeline synchronously (called in a worker thread). Returns a JSON-able dict."""
    bbox = bounds_to_bbox(bounds)
    t0 = time.perf_counter()
    candidates = search(bbox, today - timedelta(days=window_days), today, limit=6)
    log.info("S2 search: %d scenes in %.1fs", len(candidates), time.perf_counter() - t0)
    if not candidates:
        raise TooCloudy(SOURCE, f"no Sentinel-2 scene under {MAX_SCENE_CLOUD}% cloud in {window_days} days",
                        cloud_pct=None)
    measured = _stats_for(candidates, bbox)
    log.info("S2 SCL checks done at %.1fs", time.perf_counter() - t0)
    chosen = next(((it, st) for it, st in measured if st.clear >= MIN_CLEAR), None)
    if chosen is None:
        least_cloud = min(measured, key=lambda p: p[1].cloud)
        if least_cloud[1].water >= 0.5:
            raise NotFarmland(SOURCE, f"{least_cloud[1].water:.0%} of the box is water")
        newest = measured[0][1]
        cloud_pct = round(100 * (1 - newest.clear - newest.water), 1)
        raise TooCloudy(SOURCE, f"no scene in {window_days} days shows ≥ {MIN_CLEAR:.0%} of the box clearly; "
                                f"newest is {cloud_pct}% cloud", cloud_pct=cloud_pct)
    clear_now = [(it, st) for it, st in measured if st.clear >= MIN_CLEAR]
    target = _scene_date(clear_now[0][0]) - timedelta(days=365)
    skipped: list[str] = []

    def first_readable(pairs: list) -> Optional[tuple]:
        """Read clear scenes in order until one gives plausible pixels; remember why others were skipped."""
        for it, stats in pairs:
            try:
                return read_scene(it, bbox), stats
            except SceneUnusable as exc:
                skipped.append(str(exc))
                log.warning("S2 scene skipped: %s", exc)
        return None

    def last_year() -> Optional[tuple]:
        """Same weeks last year: ±15 days around (scene date − 365 days); nearest clear, readable scene wins."""
        ly_items = search(bbox, target - timedelta(days=15), target + timedelta(days=15), limit=10)
        ly_items.sort(key=lambda it: abs((_scene_date(it) - target).days))
        ly_measured = _stats_for(ly_items, bbox) if ly_items else []
        return first_readable([(it, s2) for it, s2 in ly_measured if s2.clear >= MIN_CLEAR][:3])

    with ThreadPoolExecutor(max_workers=2) as pool:
        now_f = pool.submit(first_readable, clear_now[:3])
        ly_f = pool.submit(last_year)
        picked, ly_picked = now_f.result(), ly_f.result()
    log.info("S2 band reads done at %.1fs (%d scene(s) skipped)", time.perf_counter() - t0, len(skipped))
    if picked is None:
        raise SourceUnavailable(SOURCE, "clear scenes could not be read: " + "; ".join(skipped)[:200])
    now, st = picked
    ly = ly_picked[0] if ly_picked else None
    item = now.item
    scene_day = _scene_date(item)

    ndvi_stat, ndmi_stat = _stat(now.ndvi, now.valid), _stat(now.ndmi, now.valid)
    overlays = [
        Overlay(layer="ndvi", period="now", png_base64=overlay.ndvi_png(now.ndvi, now.valid),
                bounds=now.bounds, scene_date=scene_day, masked_pct=overlay.masked_pct(now.valid)),
        Overlay(layer="truecolor", period="now", png_base64=overlay.truecolor_png(*now.rgb_dn, now.valid),
                bounds=now.bounds, scene_date=scene_day, masked_pct=overlay.masked_pct(now.valid)),
    ]
    out: dict = {"ndvi_last_year": None, "ndmi_last_year": None, "delta_ndvi": None, "delta_ndmi": None,
                 "last_year_scene_id": None, "last_year_scene_date": None}
    if ly is not None and ly.valid.any():
        ly_day = _scene_date(ly.item)
        ndvi_ly, ndmi_ly = _stat(ly.ndvi, ly.valid).median, _stat(ly.ndmi, ly.valid).median
        out.update(ndvi_last_year=ndvi_ly, ndmi_last_year=ndmi_ly,
                   delta_ndvi=round(ndvi_stat.median - ndvi_ly, 3), delta_ndmi=round(ndmi_stat.median - ndmi_ly, 3),
                   last_year_scene_id=ly.item.id, last_year_scene_date=ly_day.isoformat())
        overlays += [
            Overlay(layer="ndvi", period="last_year", png_base64=overlay.ndvi_png(ly.ndvi, ly.valid),
                    bounds=ly.bounds, scene_date=ly_day, masked_pct=overlay.masked_pct(ly.valid)),
            Overlay(layer="truecolor", period="last_year", png_base64=overlay.truecolor_png(*ly.rgb_dn, ly.valid),
                    bounds=ly.bounds, scene_date=ly_day, masked_pct=overlay.masked_pct(ly.valid)),
        ]
        if ly.ndvi.shape == now.ndvi.shape:
            both = now.valid & ly.valid
            overlays.append(Overlay(
                layer="delta_ndvi", period="now", png_base64=overlay.change_png(now.ndvi - ly.ndvi, both),
                bounds=now.bounds, scene_date=scene_day, masked_pct=overlay.masked_pct(both)))

    land_note = None
    if st.water > 0.5 or (ndvi_stat.median < 0.1 and (out["ndvi_last_year"] is None or out["ndvi_last_year"] < 0.1)):
        land_note = "This looks like a built-up area or water, not a farm. Results may not apply."
    fetched = now_ist()
    return {
        "scene_id": item.id, "scene_date": scene_day.isoformat(),
        "scene_cloud_pct": round(float(item.properties.get("eo:cloud_cover", math.nan)), 1),
        "clear_fraction": round(st.clear, 3), "water_fraction": round(st.water, 3), "window_days": window_days,
        "ndvi": ndvi_stat.model_dump(), "ndmi": ndmi_stat.model_dump(), **out, "land_note": land_note,
        "overlays": [o.model_dump(mode="json") for o in overlays],
        "source": {"name": SOURCE, "url": SOURCE_URL, "fetched_at": fetched.isoformat(),
                   "scene_date": scene_day.isoformat()},
    }


async def get_optical_index(lat: float, lon: float, bounds: list[list[float]], today: date,
                            window_days: int = 30) -> OpticalResult:
    """Async entry point: crop-health indices for the farm box, cached 24 h per location and newest scene.

    Raises TooCloudy (switch to radar), NotFarmland (water) or SourceUnavailable (Planetary Computer down/slow).
    """
    cell = f"{round(lat / 0.002) * 0.002:.3f},{round(lon / 0.002) * 0.002:.3f}"

    def run() -> dict:
        """Blocking work: search, cloud-check, read pixels and build overlays."""
        return compute(lat, lon, bounds, today, window_days)

    async def fetch() -> dict:
        """Run the pipeline in a worker thread with the satellite time budget."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(run), timeout=get_settings().satellite_timeout_s)
        except asyncio.TimeoutError as exc:
            raise SourceUnavailable(SOURCE, f"timed out after {get_settings().satellite_timeout_s:.0f} s") from exc
        except (TooCloudy, NotFarmland, SourceUnavailable):
            raise
        except Exception as exc:  # network/raster errors from the STAC client or GDAL
            raise SourceUnavailable(SOURCE, f"{type(exc).__name__}: {str(exc)[:160]}") from exc

    key = f"optical:{cell}:{today.isoformat()}:{window_days}"
    value, from_cache = await cache.cached(key, cache.TTL_SAT_NOW, SOURCE, fetch)
    result = OpticalResult.model_validate(value)
    result.source = SourceRef(**{**result.source.model_dump(), "cached": from_cache})
    return result
