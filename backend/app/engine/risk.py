"""The risk engine: transparent 0-100 scores for drought, excess/unseasonal rain and heat (F6, BUILD_SPEC §7).

Each score is a weighted sum of simple components. Each component maps one real measured value onto 0-100
with `lin(x, a, b)`. All thresholds and weights come from `risk.yaml`. Missing evidence is dropped and the
remaining weights are rescaled; with under 50% of the weight available a hazard reads "Not enough data".
This is pure code, so the same evidence always gives the same scores. The LLM never touches these numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.config import risk_rules
from app.engine.crops import heat_threshold, is_sensitive_for
from app.models import Citation, Component, Driver, RiskScore, StageInfo

ENGINE_SOURCE = "KhetKavach risk engine"


def lin(x: float, a: float, b: float) -> float:
    """Map x to 0-100: 0 at the 'no concern' point a, 100 at the 'full concern' point b, clamped."""
    return max(0.0, min(100.0, (x - a) / (b - a) * 100.0))


def level_for(score: int) -> str:
    """Level word for a score: 0-33 low, 34-66 moderate, 67-100 high."""
    levels = risk_rules()["levels"]
    if score <= levels["low_max"]:
        return "low"
    if score <= levels["moderate_max"]:
        return "moderate"
    return "high"


@dataclass
class Inputs:
    """The measured values the engine scores, plus the citation for each value.

    `values` keys: water_deficit_mm, longest_dry_run_days, soil_moisture_root, delta_ndmi, delta_vh_db,
    rain_past30_obs_mm, rain_past30_normal_mm, max_3day_rain_mm, rain_next16_mm, rain_next16_normal_mm,
    rain_prob_next7_max, tmax_series, tmax_next16_max, tmax_next16_mean, tmax_next16_normal_mean,
    ndmi_now, ndmi_last_year, vh_db, vh_db_last_year.
    """

    values: dict[str, Any]
    cites: dict[str, Citation] = field(default_factory=dict)
    radar_used: bool = False
    satellite_missing: bool = False
    forecast_missing: bool = False
    baseline_missing: bool = False

    def get(self, key: str) -> Optional[float]:
        """A value, or None when that evidence is missing."""
        return self.values.get(key)


@dataclass
class ScoreOutput:
    """Everything `score_risk` returns: three scores, overall level, confidence and the derived values."""

    scores: list[RiskScore]
    overall_level: Optional[str]
    confidence: str
    confidence_reasons: list[str]
    derived: dict[str, Any]
    headline: Optional[dict] = None


def _fmt(v: float, nd: int = 1) -> str:
    """Format a number for a sentence, dropping a trailing '.0'."""
    s = f"{v:.{nd}f}"
    return s[:-2] if s.endswith(".0") else s


class _Builder:
    """Collects components for one hazard and turns them into a RiskScore."""

    def __init__(self, hazard: str, inputs: Inputs, derived_cite: callable) -> None:
        """Start an empty component list for `hazard`."""
        self.hazard = hazard
        self.inputs = inputs
        self.derived_cite = derived_cite
        self.components: list[Component] = []
        self.texts: dict[str, Driver] = {}

    def add(self, key: str, label: str, value: Optional[float], unit: str, a: float, b: float, weight: float,
            text: Optional[str] = None, cites: Optional[list[Citation]] = None, transform=None,
            note: Optional[str] = None) -> None:
        """Add a component. `transform` turns the raw value into the lin() input (e.g. 0.30 − soil moisture)."""
        if value is None:
            self.components.append(Component(key=key, label=label, value=None, unit=unit, points=None,
                                             weight=weight, available=False, note=note or "evidence missing"))
            return
        x = transform(value) if transform else value
        self.components.append(Component(key=key, label=label, value=round(float(value), 3), unit=unit,
                                         points=round(lin(x, a, b), 1), weight=weight, note=note))
        if text:
            self.texts[key] = Driver(text=text, citations=[c for c in (cites or []) if c is not None])

    def build(self, multiplier: float) -> RiskScore:
        """Rescale weights over available components, apply the stage multiplier and pick the top 2 drivers."""
        min_fraction = risk_rules()["min_weight_fraction"]
        total = sum(c.weight for c in self.components)
        available = [c for c in self.components if c.available and c.weight > 0]
        avail_w = sum(c.weight for c in available)
        if total == 0 or avail_w / total < min_fraction:
            return RiskScore(hazard=self.hazard, score=None, level=None, components=self.components,
                             available_weight=round(avail_w, 3), status="not_enough_data")
        raw = sum(c.points * c.weight for c in available) / avail_w
        for c in available:
            c.contribution = round(c.points * c.weight / avail_w, 2)
        score = int(round(min(100.0, raw * multiplier)))
        ranked = sorted(available, key=lambda c: (c.contribution, c.weight), reverse=True)
        drivers = [self.texts[c.key] for c in ranked if c.key in self.texts][:2]
        return RiskScore(hazard=self.hazard, score=score, level=level_for(score), drivers=drivers,
                         components=self.components, available_weight=round(avail_w / total, 3),
                         multiplier=multiplier)


def score_all(inputs: Inputs, crop: str, stage: StageInfo, *, call_id: str = "score",
              fetched_at: Optional[datetime] = None) -> ScoreOutput:
    """Score the three hazards from measured inputs. `call_id` is this scoring step's id for citations."""
    rules = risk_rules()
    v = inputs.get
    derived: dict[str, Any] = {}
    fetched_at = fetched_at or datetime.now().astimezone()

    def dcite(field_name: str, unit: str = "") -> Citation:
        """Citation for a value computed by this engine (e.g. the rain anomaly)."""
        return Citation(call_id=call_id, source=ENGINE_SOURCE, field=field_name, value=derived.get(field_name),
                        unit=unit, fetched_at=fetched_at)

    c = inputs.cites.get

    # ---- derived values (all from real inputs) ----
    obs, normal30 = v("rain_past30_obs_mm"), v("rain_past30_normal_mm")
    anomaly = None
    if obs is not None and normal30 is not None and normal30 >= 5:
        anomaly = round((obs - normal30) / normal30 * 100.0, 1)
    derived["rain_past30_anomaly_pct"] = anomaly
    thr = heat_threshold(crop, stage)
    derived["heat_threshold_c"] = thr
    tmax_series = v("tmax_series")
    hot_days = sum(1 for t in tmax_series if t is not None and t >= thr) if tmax_series else None
    derived["hot_days_next16"] = hot_days
    rn16, nn16 = v("rain_next16_mm"), v("rain_next16_normal_mm")
    derived["rain_next16_vs_normal_mm"] = round(rn16 - nn16, 1) if rn16 is not None and nn16 is not None else None
    tmean, tnorm = v("tmax_next16_mean"), v("tmax_next16_normal_mean")
    derived["tmax_vs_normal_c"] = round(tmean - tnorm, 1) if tmean is not None and tnorm is not None else None
    tpeak = v("tmax_next16_max")
    derived["peak_over_threshold_c"] = round(tpeak - thr, 1) if tpeak is not None else None

    # ---- drought ----
    dr = rules["drought"]
    comp = dr["components"]
    b = _Builder("drought", inputs, dcite)
    d1_w, d2_w = comp["D1"]["weight"], comp["D2"]["weight"]
    d2_note = None
    d2_off = nn16 is not None and nn16 < dr["d2_min_normal_rain_mm"]
    if d2_off:
        d1_w, d2_w = d1_w + d2_w, 0.0
        d2_note = f"dry weeks are normal now (20-year normal {_fmt(nn16)} mm for these 16 days)"
    deficit = v("water_deficit_mm")
    b.add("D1", "Water deficit (ET0 − rain, next 16 days)", deficit, "mm", comp["D1"]["a"], comp["D1"]["b"], d1_w,
          text=(f"Evaporation will exceed rain by {_fmt(deficit)} mm over the next 16 days" if deficit is not None
                and deficit >= 0 else f"Rain will exceed evaporation by {_fmt(abs(deficit or 0))} mm over the "
                                      f"next 16 days"),
          cites=[c("water_deficit_mm")])
    dry = v("longest_dry_run_days")
    b.add("D2", "Longest dry spell (days < 2.5 mm)", dry, "days", comp["D2"]["a"], comp["D2"]["b"], d2_w,
          text=f"The forecast has a dry spell of {_fmt(dry or 0, 0)} days in a row", cites=[c("longest_dry_run_days")],
          note=d2_note)
    if d2_off and b.components[-1].available:
        b.components[-1].points = 0.0
    sm = v("soil_moisture_root")
    comfort = dr["soil_comfort_m3m3"]
    b.add("D3", "Root-zone soil moisture shortfall", sm, "m³/m³", comp["D3"]["a"], comp["D3"]["b"],
          comp["D3"]["weight"], transform=lambda s: comfort - s,
          text=f"Root-zone soil moisture is {_fmt(sm or 0, 3)} m³/m³ (comfortable is about {comfort})",
          cites=[c("soil_moisture_root")])
    if inputs.radar_used:
        dvh = v("delta_vh_db")
        b.add("D4", "Radar VH change vs last year", dvh, "dB", comp["D4_radar"]["a"], comp["D4_radar"]["b"],
              comp["D4_radar"]["weight"], transform=lambda x: -x,
              text=(f"Radar backscatter is {_fmt(dvh or 0, 2)} dB vs the same weeks last year "
                    f"({'less' if (dvh or 0) < 0 else 'more'} crop biomass)"),
              cites=[c("delta_vh_db")])
    else:
        dndmi = v("delta_ndmi")
        b.add("D4", "Crop moisture (NDMI) change vs last year", dndmi, "", comp["D4"]["a"], comp["D4"]["b"],
              comp["D4"]["weight"], transform=lambda x: -x,
              text=(f"Crop moisture index (NDMI) is {_fmt(v('ndmi_now') or 0, 3)} vs {_fmt(v('ndmi_last_year') or 0, 3)} "
                    f"in the same weeks last year"),
              cites=[c("ndmi_now"), c("ndmi_last_year")])
    b.add("D5", "Past 30 days rain below normal", anomaly, "%", comp["D5"]["a"], comp["D5"]["b"],
          comp["D5"]["weight"], transform=lambda x: -x,
          text=(f"Rain in the past 30 days was {_fmt(obs or 0)} mm, {_fmt(abs(anomaly or 0), 0)}% "
                f"{'below' if (anomaly or 0) < 0 else 'above'} the 20-year normal of {_fmt(normal30 or 0)} mm"),
          cites=[c("rain_past30_obs_mm"), c("rain_past30_normal_mm"), dcite("rain_past30_anomaly_pct", "%")],
          note=None if anomaly is not None or normal30 is None else "normal under 5 mm; anomaly not meaningful")
    drought = b.build(dr["sensitive_multiplier"] if is_sensitive_for("drought", crop, stage.key) else 1.0)

    # ---- excess / unseasonal rain ----
    ex = rules["excess_rain"]
    comp = ex["components"]
    b = _Builder("excess_rain", inputs, dcite)
    m3 = v("max_3day_rain_mm")
    b.add("E1", "Heaviest 3-day rain", m3, "mm", comp["E1"]["a"], comp["E1"]["b"], comp["E1"]["weight"],
          text=f"The heaviest 3-day rain in the forecast is {_fmt(m3 or 0)} mm", cites=[c("max_3day_rain_mm")])
    diff = derived["rain_next16_vs_normal_mm"]
    b.add("E2", "Rain above the seasonal normal", diff, "mm", comp["E2"]["a"], comp["E2"]["b"], comp["E2"]["weight"],
          text=f"Forecast rain for 16 days is {_fmt(rn16 or 0)} mm vs a normal of {_fmt(nn16 or 0)} mm",
          cites=[c("rain_next16_mm"), c("rain_next16_normal_mm"), dcite("rain_next16_vs_normal_mm", "mm")])
    pop = v("rain_prob_next7_max")
    b.add("E3", "Rain probability (next 7 days)", pop, "%", comp["E3"]["a"], comp["E3"]["b"], comp["E3"]["weight"],
          text=f"The chance of rain reaches {_fmt(pop or 0, 0)}% in the next 7 days", cites=[c("rain_prob_next7_max")])
    b.add("E4", "Waterlogging (soil moisture)", sm, "m³/m³", comp["E4"]["a"], comp["E4"]["b"], comp["E4"]["weight"],
          text=f"Root-zone soil moisture is {_fmt(sm or 0, 3)} m³/m³", cites=[c("soil_moisture_root")])
    excess = b.build(ex["sensitive_multiplier"] if is_sensitive_for("excess_rain", crop, stage.key) else 1.0)

    # ---- heat ----
    comp = rules["heat"]["components"]
    b = _Builder("heat", inputs, dcite)
    b.add("H1", f"Days at or above {_fmt(thr)} °C", hot_days, "days", comp["H1"]["a"], comp["H1"]["b"],
          comp["H1"]["weight"],
          text=(f"No day in the next 16 reaches {_fmt(thr)} °C, the heat limit for this crop stage" if hot_days == 0
                else f"{hot_days} of the next 16 days reach {_fmt(thr)} °C or more, the heat limit for this crop stage"),
          cites=[dcite("hot_days_next16", "days"), dcite("heat_threshold_c", "°C")])
    peak = derived["peak_over_threshold_c"]
    b.add("H2", "Peak temperature above the limit", peak, "°C", comp["H2"]["a"], comp["H2"]["b"], comp["H2"]["weight"],
          text=f"The hottest forecast day reaches {_fmt(tpeak or 0)} °C against a limit of {_fmt(thr)} °C",
          cites=[c("tmax_next16_max"), dcite("heat_threshold_c", "°C")])
    warm = derived["tmax_vs_normal_c"]
    b.add("H3", "Warmer than the 20-year normal", warm, "°C", comp["H3"]["a"], comp["H3"]["b"], comp["H3"]["weight"],
          text=(f"Days will average {_fmt(tmean or 0)} °C, {_fmt(abs(warm or 0))} °C "
                f"{'warmer' if (warm or 0) >= 0 else 'cooler'} than the 20-year normal of {_fmt(tnorm or 0)} °C"),
          cites=[c("tmax_next16_mean"), c("tmax_next16_normal_mean"), dcite("tmax_vs_normal_c", "°C")])
    heat = b.build(1.0)

    scores = [drought, excess, heat]
    order = {"low": 0, "moderate": 1, "high": 2}
    scored = [s for s in scores if s.level]
    overall = max((s.level for s in scored), key=order.get) if scored else None
    top = max(scored, key=lambda s: s.score) if scored else None

    reasons = []
    if inputs.radar_used:
        reasons.append("Radar used instead of optical (cloudy)")
    if inputs.satellite_missing:
        reasons.append("No satellite crop evidence")
    if inputs.baseline_missing:
        reasons.append("Historical baseline unavailable")
    if crop == "unknown":
        reasons.append("Crop not specified")
    if inputs.forecast_missing:
        reasons.append("Forecast unavailable")
    ladder = ["high", "medium", "low"]
    confidence = ladder[min(len(reasons), 2)]
    return ScoreOutput(scores=scores, overall_level=overall, confidence=confidence, confidence_reasons=reasons,
                       derived=derived,
                       headline={"hazard": top.hazard, "score": top.score, "level": top.level} if top else None)
