"""Radar fallback from Sentinel-1 via Planetary Computer, used when optical images are too cloudy (F3).

Radar sees through cloud. Lower VH backscatter than the same weeks last year suggests less crop biomass.
Primary collection: `sentinel-1-rtc` (terrain-corrected, calibrated linear gamma0). Fallback: `sentinel-1-grd`
(uncalibrated amplitude; only the change vs last year is meaningful). Confidence is one step lower than optical.
"""

from __future__ import annotations

import asyncio
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Optional

import numpy as np
import odc.stac
import pystac
from rasterio.errors import NotGeoreferencedWarning

from app import cache
from app.config import get_settings, risk_rules
from app.engine import overlay
from app.models import Overlay, RadarResult, SourceRef
from app.sources.common import SourceUnavailable, bounds_to_bbox, now_ist
from app.sources.satellite_optical import RES_DEG, catalog

WINDOW_DAYS = 24
MIN_VALID = 0.5
SOURCES = {
    "sentinel-1-rtc": ("Sentinel-1 RTC (Planetary Computer)",
                       "https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc"),
    "sentinel-1-grd": ("Sentinel-1 GRD (Planetary Computer)",
                       "https://planetarycomputer.microsoft.com/dataset/sentinel-1-grd"),
}
RTC_NODATA = -32768.0
warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)


@dataclass
class RadarArrays:
    """Backscatter in dB (and linear power) for one scene over the box."""

    item: pystac.Item
    vv_db: np.ndarray
    vh_db: np.ndarray
    ratio: np.ndarray
    valid: np.ndarray
    bounds: list[list[float]]


def _date(item: pystac.Item) -> date:
    """Acquisition date of a radar scene."""
    return datetime.fromisoformat(item.properties["datetime"].replace("Z", "+00:00")).date()


def _search(collection: str, bbox: list[float], start: date, end: date) -> list[pystac.Item]:
    """Radar scenes covering the box in a date window, newest first."""
    return list(catalog().search(
        collections=[collection], bbox=bbox, datetime=f"{start.isoformat()}/{end.isoformat()}",
        sortby=[{"field": "properties.datetime", "direction": "desc"}], max_items=8).items())


def read(item: pystac.Item, bbox: list[float], calibrated: bool) -> RadarArrays:
    """Load VV and VH for the box and convert to decibels.

    RTC values are linear power: dB = 10·log10(x). GRD values are amplitude digital numbers: power ∝ DN², so
    dB = 20·log10(DN) (uncalibrated, so only differences between scenes are meaningful).
    """
    ds = odc.stac.load([item], bands=["vv", "vh"], bbox=bbox, crs="EPSG:4326", resolution=RES_DEG,
                       resampling="nearest", pool=2).isel(time=0)
    vv, vh = ds["vv"].values.astype("float64"), ds["vh"].values.astype("float64")
    valid = np.isfinite(vv) & np.isfinite(vh) & (vv > 0) & (vh > 0) & (vv != RTC_NODATA) & (vh != RTC_NODATA)
    power_vv, power_vh = (vv, vh) if calibrated else (vv ** 2, vh ** 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        vv_db, vh_db = 10 * np.log10(power_vv), 10 * np.log10(power_vh)
        ratio = power_vh / power_vv
    bb = ds.odc.geobox.boundingbox
    return RadarArrays(item, vv_db, vh_db, ratio, valid, [[bb.bottom, bb.left], [bb.top, bb.right]])


def _median(values: np.ndarray, valid: np.ndarray) -> float:
    """Median over valid pixels."""
    return float(np.median(values[valid]))


def compute(bounds: list[list[float]], today: date, collection: str) -> dict:
    """Blocking radar pipeline: newest usable scene, the matching scene last year, medians and a change overlay."""
    bbox = bounds_to_bbox(bounds)
    calibrated = collection == "sentinel-1-rtc"
    items = _search(collection, bbox, today - timedelta(days=WINDOW_DAYS), today)
    now = None
    for item in items[:3]:
        arrays = read(item, bbox, calibrated)
        if arrays.valid.mean() >= MIN_VALID:
            now = arrays
            break
    if now is None:
        raise SourceUnavailable(SOURCES[collection][0], f"no usable radar scene in the last {WINDOW_DAYS} days")

    # Same window last year, preferring the same orbit track so the viewing geometry matches.
    ly_items = _search(collection, bbox, today - timedelta(days=WINDOW_DAYS + 365), today - timedelta(days=365))
    orbit = now.item.properties.get("sat:relative_orbit")
    ly_items.sort(key=lambda it: (it.properties.get("sat:relative_orbit") != orbit,
                                  -_date(it).toordinal()))
    ly: Optional[RadarArrays] = None
    for item in ly_items[:3]:
        arrays = read(item, bbox, calibrated)
        if arrays.valid.mean() >= MIN_VALID:
            ly = arrays
            break

    vh_now, vv_now = _median(now.vh_db, now.valid), _median(now.vv_db, now.valid)
    out = {"vh_db_last_year": None, "delta_vh_db": None, "last_year_scene_id": None, "last_year_scene_date": None}
    overlays = []
    if ly is not None:
        vh_ly = _median(ly.vh_db, ly.valid)
        out.update(vh_db_last_year=round(vh_ly, 2), delta_vh_db=round(vh_now - vh_ly, 2),
                   last_year_scene_id=ly.item.id, last_year_scene_date=_date(ly.item).isoformat())
        if ly.vh_db.shape == now.vh_db.shape:
            both = now.valid & ly.valid
            overlays.append(Overlay(
                layer="radar", period="now", bounds=now.bounds, scene_date=_date(now.item),
                png_base64=overlay.change_png(now.vh_db - ly.vh_db, both, risk_rules()["radar_change_bins_db"]),
                masked_pct=overlay.masked_pct(both)).model_dump(mode="json"))
    name, url = SOURCES[collection]
    return {
        "collection": collection, "calibrated": calibrated, "scene_id": now.item.id,
        "scene_date": _date(now.item).isoformat(), **out,
        "vh_db": round(vh_now, 2), "vv_db": round(vv_now, 2),
        "vh_vv_ratio": round(_median(now.ratio, now.valid), 3), "valid_fraction": round(float(now.valid.mean()), 3),
        "overlays": overlays,
        "source": {"name": name, "url": url, "fetched_at": now_ist().isoformat(),
                   "scene_date": _date(now.item).isoformat(),
                   "note": None if calibrated else "Uncalibrated GRD amplitude: only the change vs last year is used"},
    }


async def get_radar_index(lat: float, lon: float, bounds: list[list[float]], today: date,
                          collection: Literal["sentinel-1-rtc", "sentinel-1-grd"] = "sentinel-1-rtc") -> RadarResult:
    """Async entry point: VH backscatter now vs last year for the box (cached 24 h). Raises SourceUnavailable."""
    name = SOURCES[collection][0]

    async def fetch() -> dict:
        """Run the radar pipeline in a worker thread with the satellite time budget."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(compute, bounds, today, collection),
                                          timeout=get_settings().satellite_timeout_s)
        except asyncio.TimeoutError as exc:
            raise SourceUnavailable(name, f"timed out after {get_settings().satellite_timeout_s:.0f} s") from exc
        except SourceUnavailable:
            raise
        except Exception as exc:  # STAC / GDAL errors
            raise SourceUnavailable(name, f"{type(exc).__name__}: {str(exc)[:160]}") from exc

    cell = f"{round(lat / 0.002) * 0.002:.3f},{round(lon / 0.002) * 0.002:.3f}"
    value, from_cache = await cache.cached(f"radar:{collection}:{cell}:{today.isoformat()}",
                                           cache.TTL_SAT_NOW, name, fetch)
    result = RadarResult.model_validate(value)
    result.source = SourceRef(**{**result.source.model_dump(), "cached": from_cache})
    return result
