"""20-year historical normal for the farm: ERA5 via Open-Meteo's archive, with NASA POWER as the backup (F5).

For each year 2006-2025 we take the same calendar windows as now (the past 30 days and the next 16 days),
then average across years. That gives "normal" rain and max temperature for comparison with this year.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, Optional

from app import cache
from app.models import BaselineResult
from app.sources.common import SourceUnavailable, get_json, now_ist

FIRST_YEAR, LAST_YEAR = 2006, 2025
PAST_DAYS, NEXT_DAYS = 30, 16

ERA5_URL = "https://archive-api.open-meteo.com/v1/archive"
ERA5_SOURCE = "ERA5 via Open-Meteo Archive"
ERA5_SOURCE_URL = "https://open-meteo.com/en/docs/historical-weather-api"
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_SOURCE = "NASA POWER"
POWER_SOURCE_URL = "https://power.larc.nasa.gov/"
POWER_FILL = -999.0


def _same_day(year: int, today: date) -> date:
    """Today's month/day in another year (29 Feb becomes 28 Feb in non-leap years)."""
    try:
        return today.replace(year=year)
    except ValueError:
        return today.replace(year=year, day=28)


def compute_normals(series: dict[date, tuple[Optional[float], Optional[float]]], today: date) -> dict:
    """Average the past-30-day and next-16-day windows across all years that have complete data.

    `series` maps a date to (rain_mm, tmax_c). A year is skipped if any day in its windows is missing,
    including windows that would run past the end of the data (late December).
    """
    past_totals, next_totals = [], []
    next_rain_by_day: list[list[float]] = [[] for _ in range(NEXT_DAYS)]
    next_tmax_by_day: list[list[float]] = [[] for _ in range(NEXT_DAYS)]
    years = []
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        anchor = _same_day(year, today)
        past = [series.get(anchor - timedelta(days=k)) for k in range(PAST_DAYS, 0, -1)]
        nxt = [series.get(anchor + timedelta(days=k)) for k in range(NEXT_DAYS)]
        if any(v is None or v[0] is None for v in past) or any(v is None or None in v for v in nxt):
            continue
        years.append(year)
        past_totals.append(sum(v[0] for v in past))
        next_totals.append(sum(v[0] for v in nxt))
        for i, (rain, tmax) in enumerate(nxt):
            next_rain_by_day[i].append(rain)
            next_tmax_by_day[i].append(tmax)
    if len(years) < 10:
        raise SourceUnavailable("baseline", f"only {len(years)} complete years", code="BASELINE_TOO_SHORT")
    tmax_normal = [round(sum(d) / len(d), 1) for d in next_tmax_by_day]
    return {
        "years_used": len(years),
        "first_year": years[0],
        "last_year": years[-1],
        "rain_past30_normal_mm": round(sum(past_totals) / len(past_totals), 1),
        "rain_next16_normal_mm": round(sum(next_totals) / len(next_totals), 1),
        "rain_next16_normal_series": [round(sum(d) / len(d), 1) for d in next_rain_by_day],
        "tmax_next16_normal_c": tmax_normal,
        "tmax_next16_normal_mean": round(sum(tmax_normal) / len(tmax_normal), 1),
    }


async def _era5(lat: float, lon: float) -> dict[date, tuple[Optional[float], Optional[float]]]:
    """Download 20 years of daily rain and max temperature from the Open-Meteo archive (ERA5) in one call."""
    data = await get_json(ERA5_URL, {
        "latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "Asia/Kolkata",
        "start_date": f"{FIRST_YEAR}-01-01", "end_date": f"{LAST_YEAR}-12-31",
        "daily": "precipitation_sum,temperature_2m_max"}, ERA5_SOURCE, timeout_s=15)
    d = data["daily"]
    return {date.fromisoformat(t): (r, x) for t, r, x in zip(d["time"], d["precipitation_sum"],
                                                              d["temperature_2m_max"])}


async def _power(lat: float, lon: float) -> dict[date, tuple[Optional[float], Optional[float]]]:
    """Download the same 20 years from NASA POWER (fill value -999 means missing)."""
    data = await get_json(POWER_URL, {
        "parameters": "PRECTOTCORR,T2M_MAX", "community": "AG", "latitude": round(lat, 4),
        "longitude": round(lon, 4), "start": f"{FIRST_YEAR}0101", "end": f"{LAST_YEAR}1231",
        "format": "JSON"}, POWER_SOURCE, timeout_s=20)
    params = data["properties"]["parameter"]
    fill = data.get("header", {}).get("fill_value", POWER_FILL)
    rain, tmax = params["PRECTOTCORR"], params["T2M_MAX"]

    def clean(v: Optional[float]) -> Optional[float]:
        """Turn POWER's fill value into None."""
        return None if v is None or v == fill else float(v)

    out = {}
    for key, r in rain.items():
        day = date(int(key[:4]), int(key[4:6]), int(key[6:8]))
        out[day] = (clean(r), clean(tmax.get(key)))
    return out


def _cell(value: float) -> float:
    """Snap a coordinate to the 0.05° cache grid (about 5 km), the resolution BUILD_SPEC §11 uses for normals."""
    return round(round(value / 0.05) * 0.05, 2)


async def get_baseline(lat: float, lon: float, today: date,
                       provider: Literal["era5", "nasa_power"] = "era5") -> BaselineResult:
    """Return the 20-year normal for this point and date from the chosen provider.

    The raw 20-year daily history is cached for 30 days per 0.05° cell (and fetched for that cell's centre, so
    the cache entry is exactly what the provider returned); the windows for today are computed on every run.
    """
    clat, clon = _cell(lat), _cell(lon)
    key = f"history:{provider}:{clat:.2f},{clon:.2f}"
    name, url = (ERA5_SOURCE, ERA5_SOURCE_URL) if provider == "era5" else (POWER_SOURCE, POWER_SOURCE_URL)

    async def fetch() -> dict:
        """Download the daily history as two compact lists starting on 1 Jan of the first year."""
        series = await (_era5(clat, clon) if provider == "era5" else _power(clat, clon))
        start = date(FIRST_YEAR, 1, 1)
        days = (date(LAST_YEAR, 12, 31) - start).days + 1
        rows = [series.get(start + timedelta(days=i), (None, None)) for i in range(days)]
        return {"start": start.isoformat(), "lat": clat, "lon": clon,
                "rain": [r for r, _ in rows], "tmax": [t for _, t in rows],
                "source": {"name": name, "url": url, "fetched_at": now_ist().isoformat()}}

    value, from_cache = await cache.cached(key, cache.TTL_BASELINE, name, fetch)
    start = date.fromisoformat(value["start"])
    series = {start + timedelta(days=i): (r, t) for i, (r, t) in enumerate(zip(value["rain"], value["tmax"]))}
    out = compute_normals(series, today)
    out["provider"] = provider
    out["source"] = {**value["source"], "cached": from_cache,
                     "note": f"20-year normal for the 0.05° cell at {clat:.2f}, {clon:.2f}"}
    return BaselineResult.model_validate(out)
