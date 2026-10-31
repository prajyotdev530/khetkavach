"""16-day weather forecast and soil moisture for the farm from the Open-Meteo Forecast API (F4).

One call returns the past 30 days and the next 16 days. Everything the risk engine needs (rain totals, the
longest dry spell, the water deficit, root-zone soil moisture) is derived here in plain code, never by the LLM.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from app import cache
from app.config import risk_rules
from app.models import ForecastResult
from app.sources.common import SourceUnavailable, get_json, now_ist, round_or_none

URL = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo Forecast"
SOURCE_URL = "https://open-meteo.com/en/docs"
DAILY = ("precipitation_sum", "precipitation_probability_max", "temperature_2m_max", "temperature_2m_min",
         "et0_fao_evapotranspiration")
HOURLY = ("soil_moisture_3_to_9cm", "soil_moisture_9_to_27cm")
PAST_DAYS = 30
FORECAST_DAYS = 16


def _total(values: list[Optional[float]]) -> float:
    """Sum a series, skipping missing values."""
    return float(sum(v for v in values if v is not None))


def longest_dry_run(rain: list[Optional[float]], rainy_day_mm: float) -> int:
    """Length of the longest run of consecutive days with less than `rainy_day_mm` of rain."""
    best = run = 0
    for value in rain:
        if value is not None and value < rainy_day_mm:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def max_rolling_sum(values: list[Optional[float]], window: int = 3) -> float:
    """Highest total over any `window` consecutive days (missing days count as 0)."""
    clean = [v or 0.0 for v in values]
    if len(clean) < window:
        return float(sum(clean))
    return float(max(sum(clean[i:i + window]) for i in range(len(clean) - window + 1)))


def derive(data: dict, today: date, now: datetime) -> dict:
    """Turn the raw Open-Meteo response into the forecast fields of BUILD_SPEC §6.3.

    The series are split at today's date: the 30 days before it are "past observations" (Open-Meteo's model
    analysis), today and the 15 days after are the forecast.
    """
    daily, hourly = data["daily"], data["hourly"]
    dates = [date.fromisoformat(d) for d in daily["time"]]
    if today not in dates:
        raise SourceUnavailable(SOURCE, "forecast does not include today")
    t = dates.index(today)
    nxt = slice(t, t + FORECAST_DAYS)
    rain = daily["precipitation_sum"]
    rain_next = rain[nxt]
    et0_next = daily["et0_fao_evapotranspiration"][nxt]
    forecast_days = sum(1 for v in rain_next if v is not None)
    if forecast_days < 7:
        raise SourceUnavailable(SOURCE, f"only {forecast_days} forecast days", code="FORECAST_TOO_SHORT")

    # Root-zone soil moisture: mean of the 3-9 cm and 9-27 cm layers over the next 72 hours.
    hour_now = now.replace(minute=0, second=0, microsecond=0, tzinfo=None).isoformat(timespec="minutes")
    times = hourly["time"]
    h0 = times.index(hour_now) if hour_now in times else 0
    soil = [v for layer in HOURLY for v in hourly[layer][h0:h0 + 72] if v is not None]
    rain_prob_next7 = [v for v in daily["precipitation_probability_max"][t:t + 7] if v is not None]
    tmax_next = [v for v in daily["temperature_2m_max"][nxt] if v is not None]
    past_rain = rain[max(0, t - PAST_DAYS):t]
    rain_next16 = _total(rain_next)
    et0_next16 = _total(et0_next)
    return {
        "dates": [d.isoformat() for d in dates[nxt]],
        "rain_series": rain_next,
        "tmax_series": daily["temperature_2m_max"][nxt],
        "tmin_series": daily["temperature_2m_min"][nxt],
        "et0_series": et0_next,
        "rain_prob_series": daily["precipitation_probability_max"][nxt],
        "forecast_days": forecast_days,
        "rain_next16_mm": round(rain_next16, 1),
        "max_3day_rain_mm": round(max_rolling_sum(rain_next), 1),
        "longest_dry_run_days": longest_dry_run(rain_next, risk_rules()["rainy_day_mm"]),
        "et0_next16_mm": round(et0_next16, 1),
        "water_deficit_mm": round(et0_next16 - rain_next16, 1),
        "soil_moisture_root": round_or_none(sum(soil) / len(soil), 3) if soil else None,
        "rain_past30_obs_mm": round(_total(past_rain), 1) if len(past_rain) == PAST_DAYS else None,
        "rain_prob_next7_max": max(rain_prob_next7) if rain_prob_next7 else None,
        "tmax_next16_max": max(tmax_next) if tmax_next else None,
        "tmax_next16_mean": round(sum(tmax_next) / len(tmax_next), 1) if tmax_next else None,
    }


async def get_forecast(lat: float, lon: float, today: date) -> ForecastResult:
    """Fetch (or read from the 1-hour cache) the forecast for a point and return the derived values."""
    key = f"forecast:{lat:.2f},{lon:.2f}:{today.isoformat()}"

    async def fetch() -> dict:
        """Call Open-Meteo once with all daily and hourly fields, then derive the risk inputs."""
        params = {"latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "Asia/Kolkata",
                  "forecast_days": FORECAST_DAYS, "past_days": PAST_DAYS,
                  "daily": ",".join(DAILY), "hourly": ",".join(HOURLY)}
        data = await get_json(URL, params, SOURCE)
        fetched = now_ist()
        out = derive(data, today, fetched)
        out["source"] = {"name": SOURCE, "url": SOURCE_URL, "fetched_at": fetched.isoformat()}
        return out

    value, from_cache = await cache.cached(key, cache.TTL_FORECAST, SOURCE, fetch)
    result = ForecastResult.model_validate(value)
    result.source.cached = from_cache
    return result
