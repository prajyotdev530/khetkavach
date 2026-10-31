"""Unit tests for the risk engine (BUILD_SPEC §7 and §12): components at their a/b points, weight rescaling,
the D2 rule, stage multipliers, level boundaries and confidence steps.

These tests feed the formulas hand-picked input numbers to check the arithmetic. They are formula checks,
not data: nothing here is shown to users or stored as a response.
"""

from datetime import date

import pytest

from app.engine.crops import heat_threshold, stage_for
from app.engine.risk import Inputs, level_for, lin, score_all
from app.models import StageInfo

UNKNOWN = StageInfo(key="unknown", label="Stage unknown")


def comp(result, hazard, key):
    """Find one component of one hazard in a score_all result."""
    score = next(s for s in result.scores if s.hazard == hazard)
    return next(c for c in score.components if c.key == key)


def hazard(result, name):
    """Find one hazard's RiskScore."""
    return next(s for s in result.scores if s.hazard == name)


def test_lin_endpoints_and_clamp():
    """lin() is 0 at a, 100 at b, linear between and clamped outside."""
    assert lin(10, 10, 60) == 0
    assert lin(60, 10, 60) == 100
    assert lin(35, 10, 60) == 50
    assert lin(-5, 10, 60) == 0
    assert lin(500, 10, 60) == 100


@pytest.mark.parametrize("hz,key,field,at_a,at_b,extra", [
    ("drought", "D1", "water_deficit_mm", 10, 60, {}),
    ("drought", "D2", "longest_dry_run_days", 5, 14, {}),
    ("drought", "D3", "soil_moisture_root", 0.30, 0.12, {}),
    ("drought", "D4", "delta_ndmi", -0.02, -0.15, {}),
    ("excess_rain", "E1", "max_3day_rain_mm", 20, 80, {}),
    ("excess_rain", "E3", "rain_prob_next7_max", 40, 90, {}),
    ("excess_rain", "E4", "soil_moisture_root", 0.35, 0.45, {}),
])
def test_component_a_and_b_points(hz, key, field, at_a, at_b, extra):
    """Each directly-measured component scores 0 at its a point and 100 at its b point."""
    for value, expected in ((at_a, 0.0), (at_b, 100.0)):
        result = score_all(Inputs(values={field: value, **extra}), "wheat", UNKNOWN)
        assert comp(result, hz, key).points == pytest.approx(expected, abs=0.01)


def test_radar_d4_a_and_b():
    """With radar, D4 uses −ΔVH dB between 0.5 and 3.0."""
    for value, expected in ((-0.5, 0.0), (-3.0, 100.0)):
        result = score_all(Inputs(values={"delta_vh_db": value}, radar_used=True), "wheat", UNKNOWN)
        assert comp(result, "drought", "D4").points == pytest.approx(expected)


def test_d5_rain_anomaly_points_and_null_rule():
    """D5 uses −anomaly between 20% and 80%; it is skipped when the normal is under 5 mm."""
    at_a = score_all(Inputs(values={"rain_past30_obs_mm": 80, "rain_past30_normal_mm": 100}), "wheat", UNKNOWN)
    at_b = score_all(Inputs(values={"rain_past30_obs_mm": 20, "rain_past30_normal_mm": 100}), "wheat", UNKNOWN)
    assert at_a.derived["rain_past30_anomaly_pct"] == -20.0
    assert comp(at_a, "drought", "D5").points == pytest.approx(0)
    assert comp(at_b, "drought", "D5").points == pytest.approx(100)
    tiny = score_all(Inputs(values={"rain_past30_obs_mm": 1, "rain_past30_normal_mm": 4}), "wheat", UNKNOWN)
    assert tiny.derived["rain_past30_anomaly_pct"] is None
    assert comp(tiny, "drought", "D5").available is False


def test_e2_uses_rain_minus_normal():
    """E2 is lin(rain_next16 − normal, 10, 60)."""
    a = score_all(Inputs(values={"rain_next16_mm": 30, "rain_next16_normal_mm": 20}), "wheat", UNKNOWN)
    b = score_all(Inputs(values={"rain_next16_mm": 80, "rain_next16_normal_mm": 20}), "wheat", UNKNOWN)
    assert comp(a, "excess_rain", "E2").points == pytest.approx(0)
    assert comp(b, "excess_rain", "E2").points == pytest.approx(100)


def test_heat_components_a_and_b():
    """H1 counts hot days (0→6), H2 peak over the limit (0→5 °C), H3 warmer than normal (1→5 °C)."""
    thr = heat_threshold("unknown", UNKNOWN)  # 35 °C for 'Not sure'
    cool = score_all(Inputs(values={"tmax_series": [30.0] * 16, "tmax_next16_max": thr,
                                    "tmax_next16_mean": 31.0, "tmax_next16_normal_mean": 30.0}), "unknown", UNKNOWN)
    hot = score_all(Inputs(values={"tmax_series": [thr] * 6 + [30.0] * 10, "tmax_next16_max": thr + 5,
                                   "tmax_next16_mean": 35.0, "tmax_next16_normal_mean": 30.0}), "unknown", UNKNOWN)
    for key, lo, hi in (("H1", 0, 100), ("H2", 0, 100), ("H3", 0, 100)):
        assert comp(cool, "heat", key).points == pytest.approx(lo)
        assert comp(hot, "heat", key).points == pytest.approx(hi)
    assert hazard(hot, "heat").score == 100


def test_weight_rescaling_with_missing_evidence():
    """Missing components are dropped and the rest rescaled; under 50% of the weight gives no score."""
    # D1 (0.30) + D3 (0.20) = 0.50 available -> scored, rescaled over 0.5.
    r = score_all(Inputs(values={"water_deficit_mm": 60, "soil_moisture_root": 0.30}), "wheat", UNKNOWN)
    d = hazard(r, "drought")
    assert d.status == "ok"
    assert d.available_weight == pytest.approx(0.5)
    assert d.score == round((100 * 0.30 + 0 * 0.20) / 0.50)  # 60
    # Only D1 (0.30) -> not enough data.
    r2 = score_all(Inputs(values={"water_deficit_mm": 60}), "wheat", UNKNOWN)
    assert hazard(r2, "drought").status == "not_enough_data"
    assert hazard(r2, "drought").score is None and hazard(r2, "drought").level is None


def test_d2_rule_moves_weight_to_d1_when_dry_season():
    """When the normal next-16-day rain is under 10 mm, D2 is 0 with no weight and D1 takes its weight."""
    vals = {"water_deficit_mm": 60, "longest_dry_run_days": 14, "rain_next16_normal_mm": 5.0,
            "rain_next16_mm": 0.0, "soil_moisture_root": 0.30}
    r = score_all(Inputs(values=vals), "wheat", UNKNOWN)
    assert comp(r, "drought", "D2").weight == 0.0
    assert comp(r, "drought", "D1").weight == pytest.approx(0.45)
    # Same evidence in a normally-rainy season keeps D2 at 100 points with weight 0.15.
    r2 = score_all(Inputs(values={**vals, "rain_next16_normal_mm": 40.0}), "wheat", UNKNOWN)
    assert comp(r2, "drought", "D2").weight == pytest.approx(0.15)
    assert comp(r2, "drought", "D2").points == pytest.approx(100)


def test_stage_multipliers():
    """Drought ×1.15 at wheat crown-root initiation; excess rain ×1.3 at flowering; both capped at 100."""
    today = date(2026, 10, 31)
    cri = stage_for("wheat", date(2026, 10, 8), today)  # 23 days after sowing
    assert cri.key == "crown_root_initiation" and cri.sensitive
    # Each component scores 40 points, so the base drought score is 40 and ×1.15 gives 46.
    vals = {"water_deficit_mm": 30, "soil_moisture_root": 0.228, "longest_dry_run_days": 8.6}
    base = hazard(score_all(Inputs(values=vals), "wheat", stage_for("wheat", date(2026, 10, 25), today)), "drought")
    boosted = hazard(score_all(Inputs(values=vals), "wheat", cri), "drought")
    assert boosted.multiplier == 1.15
    assert base.score == 40
    assert boosted.score == 46
    flowering = stage_for("mustard", date(2026, 9, 20), today)  # 41 days -> flowering
    ex = hazard(score_all(Inputs(values={"max_3day_rain_mm": 80, "rain_prob_next7_max": 90,
                                         "soil_moisture_root": 0.45}), "mustard", flowering), "excess_rain")
    assert ex.multiplier == 1.3 and ex.score == 100


@pytest.mark.parametrize("score,level", [(0, "low"), (33, "low"), (34, "moderate"), (66, "moderate"),
                                         (67, "high"), (100, "high")])
def test_level_boundaries(score, level):
    """Levels: 0-33 low, 34-66 moderate, 67-100 high."""
    assert level_for(score) == level


def test_confidence_steps_and_floor():
    """Confidence starts High and drops a step per issue, never below Low."""
    full = {"water_deficit_mm": 20, "soil_moisture_root": 0.25}
    assert score_all(Inputs(values=full), "wheat", UNKNOWN).confidence == "high"
    assert score_all(Inputs(values=full, radar_used=True), "wheat", UNKNOWN).confidence == "medium"
    assert score_all(Inputs(values=full, radar_used=True), "unknown", UNKNOWN).confidence == "low"
    worst = Inputs(values=full, radar_used=True, baseline_missing=True, forecast_missing=True)
    assert score_all(worst, "unknown", UNKNOWN).confidence == "low"


def test_crop_stage_table_and_heat_thresholds():
    """Stage lookup follows the day ranges; heat limits are lower at sensitive stages."""
    today = date(2026, 10, 31)
    assert stage_for("wheat", date(2026, 10, 21), today).key == "emergence"
    assert stage_for("gram", date(2026, 6, 1), today).key == "maturity_harvest"
    assert stage_for("wheat", None, today).key == "unknown"
    assert heat_threshold("wheat", stage_for("wheat", date(2026, 10, 8), today)) == 32
    assert heat_threshold("wheat", stage_for("wheat", date(2026, 10, 25), today)) == 34
    assert heat_threshold("unknown", UNKNOWN) == 35
