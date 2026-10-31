"""Unit tests for the citation validator (BUILD_SPEC §8, §12): a correct plan passes; an invented number, a bad
citation and an out-of-window date are all caught."""

from datetime import date

from app.agent.validator import extract, matches, validate

TODAY = date(2026, 10, 31)
EVIDENCE = {
    "c2": {"water_deficit_mm": 64.3, "longest_dry_run_days": 13, "rain_next16_mm": 8.6,
           "daily": [{"date": "2026-11-03", "rain_mm": 5.4, "tmax_c": 30.9}]},
    "c3": {"rain_past30_normal_mm": 60.3, "years_used": 20},
    "c5": {"drought_score": 92, "rain_past30_anomaly_pct": -95.9},
}
CONTEXT = [16, 30, 7]


def plan(summary: str, actions: list[dict]) -> dict:
    """Build a draft in the write-step schema."""
    return {"summary": summary, "actions": actions}


def test_correct_plan_passes():
    """Every number matches a cited field (or a tool argument such as 16 days); dates are in the window."""
    draft = plan("Drought risk is high (92). Rain over the past 30 days was 96% below normal.", [
        {"by_date": "2026-11-02", "action": "Irrigate before 2 Nov",
         "reason": "Evaporation will exceed rain by 64.3 mm over the next 16 days",
         "citations": ["c2.water_deficit_mm"]},
        {"by_date": "2026-11-05", "action": "Mulch to save soil water",
         "reason": "A dry spell of 13 days is forecast", "citations": ["c2.longest_dry_run_days"]},
    ])
    report = validate(draft, EVIDENCE, TODAY, CONTEXT)
    assert report["failing_lines"] == []
    assert report["numbers_rejected"] == 0
    assert report["numbers_checked"] >= 5


def test_invented_number_is_caught():
    """A number that is not in the cited evidence is rejected and the line is flagged."""
    draft = plan("Drought risk is high.", [
        {"by_date": "2026-11-02", "action": "Irrigate now",
         "reason": "Rain is 48% below normal", "citations": ["c2.water_deficit_mm"]},
    ])
    report = validate(draft, EVIDENCE, TODAY, CONTEXT)
    assert report["numbers_rejected"] == 1
    assert report["failing_lines"][0]["line"] == "action[0]"


def test_number_must_match_the_cited_field_not_any_field():
    """64.3 is in the evidence, but this action cites a different field, so it fails."""
    draft = plan("", [{"by_date": "2026-11-02", "action": "Irrigate",
                       "reason": "Deficit of 64.3 mm", "citations": ["c2.longest_dry_run_days"]}])
    assert validate(draft, EVIDENCE, TODAY, CONTEXT)["numbers_rejected"] == 1


def test_bad_citation_fails():
    """Citations must point to a real call_id and field."""
    draft = plan("", [{"by_date": "2026-11-02", "action": "Irrigate", "reason": "Dry soil",
                       "citations": ["c9.water_deficit_mm", "c2.made_up_field"]}])
    problems = validate(draft, EVIDENCE, TODAY, CONTEXT)["failing_lines"][0]["problems"]
    assert any("c9.water_deficit_mm" in p for p in problems)
    assert any("c2.made_up_field" in p for p in problems)


def test_out_of_window_date_fails():
    """by_date must be within today..today+16."""
    draft = plan("", [{"by_date": "2026-12-25", "action": "Harvest", "reason": "Season end", "citations": []}])
    problems = validate(draft, EVIDENCE, TODAY, CONTEXT)["failing_lines"][0]["problems"]
    assert any("by_date" in p for p in problems)


def test_extract_ignores_names_and_dates():
    """'Sentinel-2', 'ERA5' and '6 Nov' are not numbers; '1,500' is 1500; Unicode minus works."""
    numbers, dates = extract("Sentinel-2 and ERA5 show NDMI −0.044 on 6 Nov, 1,500 m², a 3-day burst", TODAY)
    assert numbers == [-0.044, 1500.0, 3.0]
    assert dates == [date(2026, 11, 6)]


def test_tolerance_and_sign():
    """Within 0.5 absolute or 2% relative; sign ignored ('96% below' vs anomaly −95.9)."""
    assert matches(96, [-95.9])
    assert matches(64, [64.3])
    assert not matches(70, [64.3])
    assert matches(1010, [1000])


def test_reference_written_inside_text_fails():
    """'c2.water_deficit_mm mm' in the text instead of the number is rejected (seen in a live Gemini rewrite)."""
    draft = plan("Evaporation will exceed rain by c2.water_deficit_mm mm.", [
        {"by_date": "2026-11-02", "action": "Irrigate", "reason": "Deficit reaches c2.water_deficit_mm mm",
         "citations": ["c2.water_deficit_mm"]}])
    report = validate(draft, EVIDENCE, TODAY, CONTEXT)
    assert {f["line"] for f in report["failing_lines"]} == {"summary", "action[0]"}
