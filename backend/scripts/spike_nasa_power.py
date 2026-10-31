"""Spike: call the NASA POWER daily point API (backup historical baseline) and print its structure.

Run: `.venv/bin/python scripts/spike_nasa_power.py [lat lon]` (default: Nashik farm 20.0, 73.79).
Confirms parameter names (PRECTOTCORR, T2M_MAX), units, the fill value and the JSON path to daily values.
"""

import sys
import time

import httpx

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"


def main() -> None:
    """Fetch 2006–2025 daily rain and max temperature for one point and summarise the response."""
    lat, lon = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) == 3 else (20.0, 73.79)
    params = {
        "parameters": "PRECTOTCORR,T2M_MAX", "community": "AG",
        "latitude": lat, "longitude": lon, "start": "20060101", "end": "20251231", "format": "JSON",
    }
    t0 = time.perf_counter()
    r = httpx.get(URL, params=params, timeout=90)
    print(f"HTTP {r.status_code} in {time.perf_counter() - t0:.2f}s, {len(r.content)} bytes")
    data = r.json()
    print("top-level keys:", sorted(data.keys()))
    print("header:", {k: v for k, v in data.get("header", {}).items() if k != "sources"})
    print("parameters meta:", data.get("parameters"))
    param = data["properties"]["parameter"]
    for name, series in param.items():
        keys = list(series.keys())
        vals = list(series.values())
        fill = data.get("header", {}).get("fill_value")
        print(f"  {name}: n={len(vals)} first_key={keys[0]} last_key={keys[-1]} "
              f"fill_count={sum(v == fill for v in vals)} sample={vals[:3]}")


if __name__ == "__main__":
    main()
