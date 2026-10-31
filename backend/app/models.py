"""Pydantic schemas shared by the source modules, risk engine, agent and API (BUILD_SPEC §5).

Every tool result carries a `SourceRef` (provider name, link, fetch time, whether it came from the cache), so the
UI can show a source chip and timestamp next to every number. The frontend mirrors these types in `lib/api.ts`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Hazard = Literal["drought", "excess_rain", "heat"]
Level = Literal["low", "moderate", "high"]
Confidence = Literal["high", "medium", "low"]
Crop = Literal["wheat", "mustard", "gram", "unknown"]
Bounds = list[list[float]]  # Leaflet order: [[south, west], [north, east]]


class SourceRef(BaseModel):
    """Where a value came from: provider name, a link to the provider, and when it was fetched."""

    name: str
    url: str
    fetched_at: datetime
    cached: bool = False
    scene_date: Optional[date] = None
    note: Optional[str] = None


class Stat(BaseModel):
    """Median and spread (10th/90th percentile) of an index over the clear pixels of the farm box."""

    median: float
    p10: float
    p90: float


class Overlay(BaseModel):
    """A transparent PNG layer for the map, with the exact lat/lon bounds of its pixels."""

    layer: Literal["delta_ndvi", "ndvi", "truecolor", "radar"]
    period: Literal["now", "last_year"]
    png_base64: str
    bounds: Bounds
    scene_date: date
    masked_pct: float


class Place(BaseModel):
    """A reverse-geocoded place name for the clicked point."""

    name: str
    district: Optional[str] = None
    state: Optional[str] = None
    country_code: Optional[str] = None
    display_name: Optional[str] = None
    source: SourceRef


class SearchHit(BaseModel):
    """One place returned by village search (BUILD_SPEC §5 `/api/search`)."""

    name: str
    district: Optional[str] = None
    state: Optional[str] = None
    lat: float
    lon: float


class OpticalResult(BaseModel):
    """Sentinel-2 crop-health evidence for the 500 m box: NDVI/NDMI now and the same weeks last year."""

    scene_id: str
    scene_date: date
    scene_cloud_pct: float
    clear_fraction: float
    water_fraction: float
    window_days: int
    ndvi: Stat
    ndmi: Stat
    ndvi_last_year: Optional[float] = None
    ndmi_last_year: Optional[float] = None
    delta_ndvi: Optional[float] = None
    delta_ndmi: Optional[float] = None
    last_year_scene_id: Optional[str] = None
    last_year_scene_date: Optional[date] = None
    land_note: Optional[str] = None
    overlays: list[Overlay] = Field(default_factory=list, exclude=False)
    source: SourceRef


class RadarResult(BaseModel):
    """Sentinel-1 radar evidence used when optical images are cloudy: VH backscatter now vs last year."""

    collection: str
    calibrated: bool
    scene_id: str
    scene_date: date
    last_year_scene_id: Optional[str] = None
    last_year_scene_date: Optional[date] = None
    vh_db: float
    vv_db: float
    vh_db_last_year: Optional[float] = None
    delta_vh_db: Optional[float] = None
    vh_vv_ratio: float
    valid_fraction: float
    overlays: list[Overlay] = Field(default_factory=list)
    source: SourceRef


class ForecastResult(BaseModel):
    """Open-Meteo 16-day forecast plus the past 30 days, and the values derived from them in code."""

    dates: list[date]
    rain_series: list[Optional[float]]
    tmax_series: list[Optional[float]]
    tmin_series: list[Optional[float]]
    et0_series: list[Optional[float]]
    rain_prob_series: list[Optional[float]]
    forecast_days: int
    rain_next16_mm: float
    max_3day_rain_mm: float
    longest_dry_run_days: int
    et0_next16_mm: float
    water_deficit_mm: float
    soil_moisture_root: Optional[float] = None
    rain_past30_obs_mm: Optional[float] = None
    rain_prob_next7_max: Optional[float] = None
    tmax_next16_max: Optional[float] = None
    tmax_next16_mean: Optional[float] = None
    source: SourceRef


class BaselineResult(BaseModel):
    """20-year normal for the same calendar windows (past 30 days, next 16 days) from ERA5 or NASA POWER."""

    provider: Literal["era5", "nasa_power"]
    years_used: int
    first_year: int
    last_year: int
    rain_past30_normal_mm: float
    rain_next16_normal_mm: float
    rain_next16_normal_series: list[float]
    tmax_next16_normal_c: list[float]
    tmax_next16_normal_mean: float
    source: SourceRef


class Citation(BaseModel):
    """A pointer from a sentence to the exact tool output value it uses."""

    call_id: str
    source: str
    field: str
    value: Any
    unit: str = ""
    fetched_at: datetime


class Driver(BaseModel):
    """One plain-English reason behind a risk score, with its citations."""

    text: str
    citations: list[Citation] = Field(default_factory=list)


class Component(BaseModel):
    """One scoring component (e.g. D1 water deficit) with its input, 0-100 points and weighted contribution."""

    key: str
    label: str
    value: Optional[float]
    unit: str = ""
    points: Optional[float]
    weight: float
    contribution: float = 0.0
    available: bool = True
    note: Optional[str] = None


class RiskScore(BaseModel):
    """A hazard score (0-100), its level word and its top drivers. `score` is None when there is not enough data."""

    hazard: Hazard
    score: Optional[int]
    level: Optional[Level]
    drivers: list[Driver] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    available_weight: float = 0.0
    multiplier: float = 1.0
    status: Literal["ok", "not_enough_data"] = "ok"


class Action(BaseModel):
    """One dated, concrete action in the plan, with the evidence it is based on."""

    by_date: date
    action: str
    reason: str
    citations: list[Citation] = Field(default_factory=list)
    lang: str = "en-IN"
    english_fallback: bool = False


class StageInfo(BaseModel):
    """The crop stage computed from the sowing date (or 'unknown' without one)."""

    key: str
    label: str
    days_after_sowing: Optional[int] = None
    sensitive: bool = False


class Analysis(BaseModel):
    """A complete saved analysis: inputs, evidence, scores, plan and the trace (BUILD_SPEC §5)."""

    id: str
    created_at: datetime
    lat: float
    lon: float
    place: Optional[Place] = None
    crop: Crop
    sowing_date: Optional[date] = None
    stage: StageInfo
    bounds: Bounds
    evidence: dict[str, Any] = Field(default_factory=dict)
    scores: list[RiskScore] = Field(default_factory=list)
    overall_level: Optional[Level] = None
    confidence: Confidence = "high"
    confidence_reasons: list[str] = Field(default_factory=list)
    summary: str = ""
    actions: list[Action] = Field(default_factory=list)
    plan_source: Literal["llm", "rules"] = "llm"
    missing: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
