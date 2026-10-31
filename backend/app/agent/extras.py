"""P1 features built on the same tools and risk engine as the main agent:

- `assess_point` (F13 batch view): a quick, LLM-free risk check for one point: place, Sentinel-2 (or radar if
  cloudy), forecast and baseline in parallel, then the risk engine. Used for 5-20 farms at once.
- `answer_question` (F11 voice question): a grounded answer to a farmer's question using only one saved
  analysis's tool outputs, with every number checked by the citation validator.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, Optional

from app.agent import llm, tools
from app.agent.graph import _citation_objects, _context_numbers, _evidence_for_llm
from app.agent.validator import validate
from app.engine.crops import CROP_LABELS
from app.engine.risk import score_all
from app.models import StageInfo
from app.sources import geocode
from app.sources.common import NotFarmland, SourceUnavailable, TooCloudy, analysis_box, now_ist, today_ist

UNKNOWN_STAGE = StageInfo(key="unknown", label="Stage unknown")


async def _try(tool: str, args: dict, *, lat: float, lon: float, bounds: list, today: date) -> Optional[Any]:
    """Run one tool; None if it fails (the batch view marks that evidence missing)."""
    try:
        return await tools.execute(tool, args, lat=lat, lon=lon, bounds=bounds, today=today, fail=None)
    except (SourceUnavailable, Exception):  # noqa: BLE001 - any failure means "missing" for this point
        return None


async def _satellite(lat: float, lon: float, bounds: list, today: date) -> tuple[Optional[str], Optional[Any]]:
    """Sentinel-2 first; radar when the box is cloudy (same fallback rule as the agent)."""
    try:
        return "optical", await tools.execute("get_optical_index", {"window_days": 30}, lat=lat, lon=lon,
                                              bounds=bounds, today=today, fail=None)
    except NotFarmland:
        return None, None
    except (TooCloudy, SourceUnavailable):
        radar = await _try("get_radar_index", {"collection": "sentinel-1-rtc"}, lat=lat, lon=lon, bounds=bounds,
                           today=today)
        return ("radar", radar) if radar else (None, None)


async def assess_point(index: int, lat: float, lon: float, crop: str, label: Optional[str]) -> dict:
    """Quick risk for one point: scores, overall level, confidence and what was missing (no LLM, no plan)."""
    today = today_ist()
    base = {"index": index, "label": label, "lat": lat, "lon": lon}
    try:
        place = (await geocode.reverse(lat, lon)).model_dump(mode="json")
    except geocode.RejectedLocation:
        return {**base, "status": "rejected", "message": "Outside India or over water"}
    except SourceUnavailable:
        place = {"name": geocode.coordinates_label(lat, lon)}
    bounds = analysis_box(lat, lon)
    (kind, sat), forecast, baseline = await asyncio.gather(
        _satellite(lat, lon, bounds, today),
        _try("get_forecast", {}, lat=lat, lon=lon, bounds=bounds, today=today),
        _try("get_baseline", {"provider": "era5"}, lat=lat, lon=lon, bounds=bounds, today=today))
    if baseline is None:
        baseline = await _try("get_baseline", {"provider": "nasa_power"}, lat=lat, lon=lon, bounds=bounds, today=today)
    evidence: dict[str, dict] = {}
    for i, (k, result) in enumerate(((kind, sat), ("forecast", forecast), ("baseline", baseline)), start=1):
        if k and result is not None:
            evidence[k] = {"call_id": f"c{i}", "tool": k, "args": {}, "result": result.model_dump(mode="json")}
    out = score_all(tools.build_inputs(evidence), crop, UNKNOWN_STAGE, call_id="c4", fetched_at=now_ist())
    missing = [n for k, n in (("forecast", "Forecast"), ("baseline", "Historical baseline")) if k not in evidence]
    if "optical" not in evidence and "radar" not in evidence:
        missing.insert(0, "Satellite crop health")
    return {
        **base, "status": "ok", "place": place,
        "scores": [{"hazard": s.hazard, "score": s.score, "level": s.level,
                    "top_driver": s.drivers[0].text if s.drivers else None} for s in out.scores],
        "overall_level": out.overall_level, "headline": out.headline, "confidence": out.confidence,
        "satellite": kind, "missing": missing,
        "sources": sorted({r.source.name for r in (sat, forecast, baseline) if r is not None}),
        "fetched_at": now_ist().isoformat(),
    }


def _state_from_payload(payload: dict) -> dict:
    """Rebuild the parts of the agent state that the citation helpers need from a saved analysis."""
    return {"evidence": payload.get("evidence", {}), "scores": payload["score_call"],
            "today": payload.get("today") or today_ist().isoformat()}


async def answer_question(payload: dict, question_en: str) -> dict:
    """Answer an English question from one analysis's evidence only. Rewrites once if a number is not cited
    correctly; if it still fails (or Gemini is unavailable) falls back to the top risk driver, which is cited."""
    state = _state_from_payload(payload)
    evidence = _evidence_for_llm(state)
    context = _context_numbers(state)
    today = date.fromisoformat(state["today"])
    prompt = (f"Crop: {CROP_LABELS.get(payload.get('crop'), payload.get('crop'))}. Stage: {payload['stage']['label']}. "
              f"Today: {today.isoformat()}.\nPLAN SUMMARY: {payload.get('summary', '')}\n"
              f"EVIDENCE (call_id → fields): {json.dumps(evidence, ensure_ascii=False)}\nQUESTION: {question_en}")
    problems: list = []
    for attempt in range(2):
        try:
            text = prompt if not problems else prompt + "\nYour previous answer failed the citation check: " + \
                "; ".join(p for f in problems for p in f["problems"]) + ". Answer again."
            out = await llm.answer(text)
        except llm.LLMUnavailable:
            break
        draft = {"summary": "", "actions": [{"by_date": today.isoformat(), "action": out["answer"], "reason": "",
                                             "citations": out.get("citations", [])}]}
        report = validate(draft, evidence, today, context)
        if not report["failing_lines"]:
            return {"answer": out["answer"], "citations": [c.model_dump(mode="json") for c in
                                                           _citation_objects(out.get("citations", []), state)],
                    "source": "llm", "validation": report}
        problems = report["failing_lines"]
    # Rule-based fallback: the highest-scoring hazard's top driver (already cited) + where to ask.
    scored = [s for s in state["scores"]["scores"] if s.get("score") is not None and s.get("drivers")]
    top = max(scored, key=lambda s: s["score"]) if scored else None
    if top:
        d = top["drivers"][0]
        text = (f"From this analysis: {d['text']}. For anything beyond the data shown here, consult your local KVK "
                f"or agriculture officer.")
        return {"answer": text, "citations": d["citations"], "source": "rules", "validation": None}
    return {"answer": "This analysis does not have enough data to answer that. Please consult your local KVK or "
                      "agriculture officer.", "citations": [], "source": "rules", "validation": None}
