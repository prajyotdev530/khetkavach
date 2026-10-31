"""Spike: call the Open-Meteo forecast and historical (ERA5) APIs for one farm and print what comes back.

Run: `.venv/bin/python scripts/spike_openmeteo.py [lat lon]` (default: Nashik farm 20.0, 73.79).
Confirms the exact variable names, units, series lengths and how long the 20-year archive call takes.
"""

import sys
import time

import httpx

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def spike_forecast(lat: float, lon: float) -> None:
    """Fetch the 16-day forecast + 30 past days with the fields the spec names and print a summary."""
    params = {
        "latitude": lat, "longitude": lon, "timezone": "Asia/Kolkata",
        "forecast_days": 16, "past_days": 30,
        "daily": "precipitation_sum,precipitation_probability_max,temperature_2m_max,temperature_2m_min,"
                 "et0_fao_evapotranspiration",
        "hourly": "soil_moisture_3_to_9cm,soil_moisture_9_to_27cm",
    }
    t0 = time.perf_counter()
    r = httpx.get(FORECAST_URL, params=params, timeout=20)
    print(f"== forecast HTTP {r.status_code} in {time.perf_counter() - t0:.2f}s  url={r.url}")
    data = r.json()
    print("top-level keys:", sorted(data.keys()))
    print("daily_units:", data.get("daily_units"))
    print("hourly_units:", data.get("hourly_units"))
    daily, hourly = data["daily"], data["hourly"]
    print("daily days:", len(daily["time"]), daily["time"][0], "→", daily["time"][-1])
    for k in daily:
        if k != "time":
            vals = daily[k]
            print(f"  {k}: n={len(vals)} nulls={sum(v is None for v in vals)} last16={vals[-16:]}")
    print("hourly hours:", len(hourly["time"]), hourly["time"][0], "→", hourly["time"][-1])
    for k in hourly:
        if k != "time":
            vals = hourly[k]
            print(f"  {k}: n={len(vals)} nulls={sum(v is None for v in vals)} sample={vals[720:726]}")


def spike_archive(lat: float, lon: float) -> None:
    """Fetch 20 years (2006–2025) of daily rain and max temperature in one call and report size and timing."""
    params = {
        "latitude": lat, "longitude": lon, "timezone": "Asia/Kolkata",
        "start_date": "2006-01-01", "end_date": "2025-12-31",
        "daily": "precipitation_sum,temperature_2m_max",
    }
    t0 = time.perf_counter()
    r = httpx.get(ARCHIVE_URL, params=params, timeout=60)
    print(f"\n== archive HTTP {r.status_code} in {time.perf_counter() - t0:.2f}s, {len(r.content)} bytes")
    data = r.json()
    if r.status_code != 200:
        print(data)
        return
    print("top-level keys:", sorted(data.keys()), "daily_units:", data.get("daily_units"))
    d = data["daily"]
    print("days:", len(d["time"]), d["time"][0], "→", d["time"][-1])
    for k in ("precipitation_sum", "temperature_2m_max"):
        vals = d[k]
        print(f"  {k}: nulls={sum(v is None for v in vals)} first={vals[:3]} last={vals[-3:]}")


def main() -> None:
    """Run both Open-Meteo probes."""
    lat, lon = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) == 3 else (20.0, 73.79)
    spike_forecast(lat, lon)
    spike_archive(lat, lon)


if __name__ == "__main__":
    main()
