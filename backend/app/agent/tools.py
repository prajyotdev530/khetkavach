"""The agent's typed tool layer: the tool catalogue, how each tool runs, its allowed fallbacks, and how its
output is flattened into citable evidence fields (BUILD_SPEC §8).

The LLM only chooses tools and fallbacks from these fixed lists. The latitude and longitude always come from the
user's request, never from the model, so the agent cannot fetch data for the wrong place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from app.engine.risk import Inputs
from app.models import BaselineResult, Citation, ForecastResult, OpticalResult, RadarResult
from app.sources import baseline, satellite_optical, satellite_radar, weather
from app.sources.common import NotFarmland, SourceUnavailable, TooCloudy

# Tool catalogue shown to the LLM (names and argument choices are fixed; `reason` is always required).
CATALOGUE: dict[str, dict] = {
    "get_optical_index": {
        "description": "Sentinel-2 crop health (NDVI greenness, NDMI crop moisture) for the 500 m farm box, now "
                       "vs the same weeks last year. Needs a clear (not cloudy) image.",
        "params": {"window_days": {"type": "integer", "enum": [30, 45],
                                   "description": "How many past days to search for a clear image."}},
    },
    "get_radar_index": {
        "description": "Sentinel-1 radar backscatter (VH/VV) now vs last year; sees through cloud. Use when "
                       "optical images are cloudy.",
        "params": {"collection": {"type": "string", "enum": ["sentinel-1-rtc", "sentinel-1-grd"]}},
    },
    "get_forecast": {
        "description": "Open-Meteo 16-day forecast: daily rain, rain probability, max/min temperature, "
                       "evapotranspiration, root-zone soil moisture, plus the past 30 days of rain.",
        "params": {},
    },
    "get_baseline": {
        "description": "20-year (2006-2025) normal rain and max temperature for the same calendar windows, to "
                       "compute anomalies.",
        "params": {"provider": {"type": "string", "enum": ["era5", "nasa_power"]}},
    },
}
DEFAULT_ARGS = {"get_optical_index": {"window_days": 30}, "get_radar_index": {"collection": "sentinel-1-rtc"},
                "get_forecast": {}, "get_baseline": {"provider": "era5"}}
REQUIRED = ("get_optical_index", "get_forecast", "get_baseline")
KIND = {"get_optical_index": "optical", "get_radar_index": "radar", "get_forecast": "forecast",
        "get_baseline": "baseline"}
FAIL_GROUP = {"get_optical_index": "satellite", "get_radar_index": "satellite", "get_forecast": "forecast",
              "get_baseline": "baseline"}


# Last known outcome per tool, reported by /health ("ok" or "degraded").
STATUS: dict[str, str] = {}


def record(tool: str, ok: bool) -> None:
    """Remember whether the latest call of a tool worked, for the health endpoint."""
    STATUS[tool] = "ok" if ok else "degraded"


@dataclass
class Option:
    """One allowed recovery choice for a failed call."""

    id: str
    label: str
    tool: Optional[str] = None
    args: Optional[dict] = None


MARK_MISSING = Option("mark_missing", "Mark this evidence as missing and continue")


def allowed_fallbacks(tool: str, args: dict, error_code: str, attempt: int) -> list[Option]:
    """The fallback table of BUILD_SPEC §8, as concrete options for one failed call."""
    if tool == "get_optical_index":
        if error_code == "NOT_FARMLAND":
            return [MARK_MISSING]
        opts = []
        if args.get("window_days", 30) < 45:
            opts.append(Option("optical_45", "Retry Sentinel-2 with a 45-day window", tool,
                               {"window_days": 45}))
        opts.append(Option("radar_rtc", "Switch to Sentinel-1 radar (RTC)", "get_radar_index",
                           {"collection": "sentinel-1-rtc"}))
        return opts
    if tool == "get_radar_index":
        if args.get("collection") == "sentinel-1-rtc":
            return [Option("radar_grd", "Use the Sentinel-1 GRD collection", tool,
                           {"collection": "sentinel-1-grd"}), MARK_MISSING]
        return [MARK_MISSING]
    if tool == "get_forecast":
        return [Option("forecast_retry", "Retry the forecast once", tool, {}), MARK_MISSING] if attempt == 0 \
            else [MARK_MISSING]
    if tool == "get_baseline":
        if args.get("provider", "era5") == "era5":
            return [Option("baseline_power", "Switch to NASA POWER", tool, {"provider": "nasa_power"}),
                    MARK_MISSING]
        return [MARK_MISSING]
    return [MARK_MISSING]


def fmt_day(d: Any) -> str:
    """'2026-10-30' → '30 Oct 2026' for trace labels."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%-d %b %Y")


def start_label(tool: str, args: dict) -> str:
    """Plain-English label for a tool call starting."""
    if tool == "get_optical_index":
        return f"Searching Sentinel-2 images from the last {args.get('window_days', 30)} days"
    if tool == "get_radar_index":
        return ("Reading Sentinel-1 radar (sees through cloud)" if args.get("collection") != "sentinel-1-grd"
                else "Reading Sentinel-1 GRD radar (uncalibrated backup)")
    if tool == "get_forecast":
        return "Fetching the 16-day forecast and soil moisture"
    if tool == "get_baseline":
        return ("Computing the 20-year normal from ERA5" if args.get("provider", "era5") == "era5"
                else "Computing the 20-year normal from NASA POWER")
    return tool


async def execute(tool: str, args: dict, *, lat: float, lon: float, bounds: list, today: date,
                  fail: Optional[str]) -> Any:
    """Run one tool with the request's coordinates. A demo `fail` value simulates that source's outage."""
    if fail and FAIL_GROUP.get(tool) == fail:
        raise SourceUnavailable(tool, f"Simulated outage: {fail} (demo control)", code="SIMULATED_OUTAGE")
    if tool == "get_optical_index":
        return await satellite_optical.get_optical_index(lat, lon, bounds, today, int(args.get("window_days", 30)))
    if tool == "get_radar_index":
        return await satellite_radar.get_radar_index(lat, lon, bounds, today,
                                                     args.get("collection", "sentinel-1-rtc"))
    if tool == "get_forecast":
        return await weather.get_forecast(lat, lon, today)
    if tool == "get_baseline":
        return await baseline.get_baseline(lat, lon, today, args.get("provider", "era5"))
    raise ValueError(f"unknown tool {tool}")


def error_code(exc: Exception) -> str:
    """Short machine code for a tool failure."""
    if isinstance(exc, (TooCloudy, NotFarmland, SourceUnavailable)):
        return exc.code
    return "TOOL_ERROR"


def summary(tool: str, result: Any) -> str:
    """One-line summary of a tool's output for the trace row."""
    if isinstance(result, OpticalResult):
        ly = f" (last year {result.ndvi_last_year})" if result.ndvi_last_year is not None else ""
        return (f"Scene {fmt_day(result.scene_date)} · {round(result.clear_fraction * 100)}% of box clear · "
                f"NDVI {result.ndvi.median}{ly}")
    if isinstance(result, RadarResult):
        ly = f" vs {result.vh_db_last_year} dB last year" if result.vh_db_last_year is not None else ""
        return f"Scene {fmt_day(result.scene_date)} · VH {result.vh_db} dB{ly}"
    if isinstance(result, ForecastResult):
        return (f"16 days: {result.rain_next16_mm} mm rain, longest dry spell {result.longest_dry_run_days} days, "
                f"max {result.tmax_next16_max} °C")
    if isinstance(result, BaselineResult):
        return (f"{result.years_used}-year normal: {result.rain_next16_normal_mm} mm rain for these 16 days, "
                f"{result.tmax_next16_normal_mean} °C average max")
    return ""


def evidence_fields(result: Any) -> dict[str, Any]:
    """Flatten a tool result into the citable fields the LLM sees and the validator checks."""
    if isinstance(result, OpticalResult):
        return {
            "scene_date": result.scene_date.isoformat(), "scene_cloud_pct": result.scene_cloud_pct,
            "box_clear_pct": round(result.clear_fraction * 100, 1), "window_days": result.window_days,
            "ndvi": result.ndvi.median, "ndvi_p10": result.ndvi.p10, "ndvi_p90": result.ndvi.p90,
            "ndmi": result.ndmi.median, "ndvi_last_year": result.ndvi_last_year,
            "ndmi_last_year": result.ndmi_last_year, "delta_ndvi": result.delta_ndvi,
            "delta_ndmi": result.delta_ndmi,
            "last_year_scene_date": result.last_year_scene_date.isoformat() if result.last_year_scene_date else None,
        }
    if isinstance(result, RadarResult):
        return {
            "scene_date": result.scene_date.isoformat(), "vh_db": result.vh_db, "vv_db": result.vv_db,
            "vh_db_last_year": result.vh_db_last_year, "delta_vh_db": result.delta_vh_db,
            "last_year_scene_date": result.last_year_scene_date.isoformat() if result.last_year_scene_date else None,
            "calibrated": result.calibrated,
        }
    if isinstance(result, ForecastResult):
        daily = [{"date": d.isoformat(), "rain_mm": r, "tmax_c": t, "rain_prob_pct": p}
                 for d, r, t, p in zip(result.dates, result.rain_series, result.tmax_series, result.rain_prob_series)]
        return {
            "forecast_days": result.forecast_days, "rain_next16_mm": result.rain_next16_mm,
            "max_3day_rain_mm": result.max_3day_rain_mm, "longest_dry_run_days": result.longest_dry_run_days,
            "et0_next16_mm": result.et0_next16_mm, "water_deficit_mm": result.water_deficit_mm,
            "soil_moisture_root": result.soil_moisture_root, "rain_past30_obs_mm": result.rain_past30_obs_mm,
            "rain_prob_next7_max": result.rain_prob_next7_max, "tmax_next16_max": result.tmax_next16_max,
            "tmax_next16_mean": result.tmax_next16_mean, "daily": daily,
        }
    if isinstance(result, BaselineResult):
        return {
            "provider": result.provider, "years_used": result.years_used, "first_year": result.first_year,
            "last_year": result.last_year, "rain_past30_normal_mm": result.rain_past30_normal_mm,
            "rain_next16_normal_mm": result.rain_next16_normal_mm,
            "tmax_next16_normal_mean": result.tmax_next16_normal_mean,
        }
    return {}


RESULT_TYPES = {"optical": OpticalResult, "radar": RadarResult, "forecast": ForecastResult,
                "baseline": BaselineResult}


def load_result(kind: str, data: dict) -> Any:
    """Rebuild a typed result from its stored JSON form."""
    return RESULT_TYPES[kind].model_validate(data)


def _cite(call_id: str, result: Any, field: str, value: Any, unit: str = "") -> Citation:
    """Citation for one field of one tool call."""
    return Citation(call_id=call_id, source=result.source.name, field=field, value=value, unit=unit,
                    fetched_at=result.source.fetched_at)


def build_inputs(evidence: dict[str, dict]) -> Inputs:
    """Map the gathered evidence (kind → {call_id, result}) onto risk-engine inputs with a citation per value."""
    values: dict[str, Any] = {}
    cites: dict[str, Citation] = {}

    def put(key: str, call_id: str, result: Any, field: str, value: Any, unit: str = "") -> None:
        """Record one input value and its citation (skipping missing values)."""
        if value is None:
            return
        values[key] = value
        cites[key] = _cite(call_id, result, field, value, unit)

    radar_used = False
    if "forecast" in evidence:
        cid, f = evidence["forecast"]["call_id"], load_result("forecast", evidence["forecast"]["result"])
        for key, unit in (("water_deficit_mm", "mm"), ("longest_dry_run_days", "days"), ("soil_moisture_root", "m³/m³"),
                          ("rain_past30_obs_mm", "mm"), ("max_3day_rain_mm", "mm"), ("rain_next16_mm", "mm"),
                          ("rain_prob_next7_max", "%"), ("tmax_next16_max", "°C"), ("tmax_next16_mean", "°C")):
            put(key, cid, f, key, getattr(f, key), unit)
        values["tmax_series"] = f.tmax_series
    if "baseline" in evidence:
        cid, b = evidence["baseline"]["call_id"], load_result("baseline", evidence["baseline"]["result"])
        for key, unit in (("rain_past30_normal_mm", "mm"), ("rain_next16_normal_mm", "mm"),
                          ("tmax_next16_normal_mean", "°C")):
            put(key, cid, b, key, getattr(b, key), unit)
    if "optical" in evidence:
        cid, o = evidence["optical"]["call_id"], load_result("optical", evidence["optical"]["result"])
        put("delta_ndmi", cid, o, "delta_ndmi", o.delta_ndmi)
        put("ndmi_now", cid, o, "ndmi", o.ndmi.median)
        put("ndmi_last_year", cid, o, "ndmi_last_year", o.ndmi_last_year)
    elif "radar" in evidence:
        radar_used = True
        cid, r = evidence["radar"]["call_id"], load_result("radar", evidence["radar"]["result"])
        put("delta_vh_db", cid, r, "delta_vh_db", r.delta_vh_db, "dB")
        put("vh_db", cid, r, "vh_db", r.vh_db, "dB")
        put("vh_db_last_year", cid, r, "vh_db_last_year", r.vh_db_last_year, "dB")
    return Inputs(values=values, cites=cites, radar_used=radar_used,
                  satellite_missing="optical" not in evidence and "radar" not in evidence,
                  forecast_missing="forecast" not in evidence, baseline_missing="baseline" not in evidence)


def iso(dt: datetime) -> str:
    """ISO 8601 string of a datetime (kept here so tools and graph format times the same way)."""
    return dt.isoformat()
