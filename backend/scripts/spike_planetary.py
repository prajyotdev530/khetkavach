"""Spike: check that Microsoft Planetary Computer serves Sentinel-2 and Sentinel-1 for a real farm.

Run: `.venv/bin/python scripts/spike_planetary.py [lat lon]` (default: a farm near Nashik, 20.0, 73.79).
It prints real catalogue metadata and pixel statistics so we can confirm property names, asset keys,
the Sentinel-2 reflectance offset and the Sentinel-1 value units before writing the source modules.
Nothing is saved; this is a read-only probe.
"""

import math
import sys
from datetime import date, timedelta

import numpy as np
import odc.stac
import planetary_computer
import pystac_client

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"


def box(lat: float, lon: float, half_m: float = 250.0) -> list[float]:
    """Return [west, south, east, north] for a square of 2*half_m metres centred on the point."""
    dlat = half_m / 111_320
    dlon = half_m / (111_320 * math.cos(math.radians(lat)))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def show_collection_notes(client: pystac_client.Client, collection_id: str) -> None:
    """Print the parts of the collection description that mention offsets, baselines or units."""
    coll = client.get_collection(collection_id)
    text = coll.description or ""
    print(f"\n== Collection {collection_id}: description length {len(text)}")
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in ("offset", "baseline", "harmoni", "gamma", "linear", "db", "terms", "licen")):
            print("  |", line.strip()[:300])
    print("  item_assets keys:", sorted((coll.extra_fields.get("item_assets") or {}).keys()))


def spike_sentinel2(client: pystac_client.Client, bbox: list[float]) -> None:
    """Search the last 30 days of Sentinel-2 L2A and read the 500 m box of the newest scene."""
    end = date.today()
    start = end - timedelta(days=30)
    search = client.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": 80}},
        sortby=[{"field": "properties.datetime", "direction": "desc"}],
        max_items=6,
    )
    items = list(search.items())
    print(f"\n== Sentinel-2 L2A: {len(items)} scenes in {start}..{end} with cloud < 80%")
    for it in items:
        p = it.properties
        print(f"  {it.id}  {p['datetime'][:10]}  cloud={p.get('eo:cloud_cover')}  "
              f"baseline={p.get('s2:processing_baseline')!r}  boa_offset_applied={p.get('earthsearch:boa_offset_applied')}")
    if not items:
        return
    it = items[0]
    print("  asset keys:", sorted(it.assets.keys()))
    print("  properties keys:", sorted(it.properties.keys()))
    ds = odc.stac.load(
        [it],
        bands=["B02", "B03", "B04", "B08", "B11", "SCL"],
        bbox=bbox,
        resolution=10,
        crs="EPSG:32643" if 72 <= (bbox[0] + bbox[2]) / 2 < 78 else None,
        resampling={"B11": "bilinear", "SCL": "nearest", "*": "nearest"},
    )
    print("  loaded dims:", dict(ds.sizes), "crs:", ds.odc.crs)
    for b in ["B02", "B03", "B04", "B08", "B11", "SCL"]:
        arr = ds[b].values[0].astype("float64")
        print(f"  {b}: dtype={ds[b].dtype} min={arr.min():.0f} p10={np.percentile(arr, 10):.0f} "
              f"median={np.median(arr):.0f} max={arr.max():.0f} nodata={ds[b].attrs.get('nodata')}")
    scl = ds["SCL"].values[0]
    vals, counts = np.unique(scl, return_counts=True)
    print("  SCL class counts:", dict(zip(vals.tolist(), counts.tolist())))


def spike_sentinel1(client: pystac_client.Client, bbox: list[float], collection: str) -> None:
    """Search the last 24 days of a Sentinel-1 collection and read VV/VH for the box."""
    end = date.today()
    start = end - timedelta(days=24)
    try:
        items = list(client.search(
            collections=[collection], bbox=bbox,
            datetime=f"{start.isoformat()}/{end.isoformat()}",
            sortby=[{"field": "properties.datetime", "direction": "desc"}], max_items=4,
        ).items())
    except Exception as exc:  # noqa: BLE001 - spike: report any access problem verbatim
        print(f"\n== {collection}: search failed: {type(exc).__name__}: {exc}")
        return
    print(f"\n== {collection}: {len(items)} scenes in {start}..{end}")
    for it in items:
        p = it.properties
        print(f"  {it.id}  {p['datetime'][:10]}  orbit={p.get('sat:orbit_state')}  "
              f"pol={p.get('sar:polarizations')}")
    if not items:
        return
    it = items[0]
    print("  asset keys:", sorted(it.assets.keys()))
    try:
        ds = odc.stac.load([it], bands=["vv", "vh"], bbox=bbox, resolution=10, crs="EPSG:32643")
        for b in ["vv", "vh"]:
            arr = ds[b].values[0].astype("float64")
            good = arr[np.isfinite(arr) & (arr > 0)]
            print(f"  {b}: dtype={ds[b].dtype} nodata={ds[b].attrs.get('nodata')} n={good.size} "
                  f"median={np.median(good) if good.size else float('nan'):.5f} "
                  f"→ dB={10 * np.log10(np.median(good)) if good.size else float('nan'):.2f}")
    except Exception as exc:  # noqa: BLE001
        print(f"  pixel read failed: {type(exc).__name__}: {exc}")


def main() -> None:
    """Run the Sentinel-2 and Sentinel-1 probes for one point."""
    lat, lon = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) == 3 else (20.0, 73.79)
    bbox = box(lat, lon)
    print("point", lat, lon, "bbox", [round(v, 6) for v in bbox])
    client = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    show_collection_notes(client, "sentinel-2-l2a")
    show_collection_notes(client, "sentinel-1-rtc")
    spike_sentinel2(client, bbox)
    spike_sentinel1(client, bbox, "sentinel-1-rtc")
    spike_sentinel1(client, bbox, "sentinel-1-grd")


if __name__ == "__main__":
    main()
