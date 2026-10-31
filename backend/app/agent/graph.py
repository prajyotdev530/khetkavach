"""The KhetKavach agent: a LangGraph state graph that plans, gathers evidence, recovers, scores, writes and
validates a cited action plan (F7, F8, F10; BUILD_SPEC §8).

Node order: check_location → plan → gather → check → (recover → gather, at most 2 rounds) → score → write →
validate (→ write once more if numbers were rejected) → localise → save.

The LLM does three jobs (plan, recover, write) within a budget of 4 calls; each has a deterministic fallback, so
a model outage never stops a run. Every node emits live events for the trace panel. Each node also watches the
45 s run deadline so the user always gets a (possibly partial) result.
"""

from __future__ import annotations

import asyncio
import json
import operator
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Optional, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app import cache
from app.agent import llm, tools
from app.agent.prompts import FORMAT_NOTE, REWRITE_NOTE
from app.agent.validator import validate
from app.config import get_settings, risk_rules
from app.engine.crops import CROP_LABELS, stage_for
from app.engine.risk import ENGINE_SOURCE, score_all
from app.events import Emitter, jsonable
from app.models import Action, Analysis, Citation, Place, RiskScore, StageInfo
from app.sources import baseline as baseline_src
from app.sources import geocode
from app.sources.common import SourceUnavailable, TooCloudy, analysis_box, now_ist

MAX_ROUNDS = 2
WRITE_RESERVE_S = 9.0     # time kept free after gathering for scoring, writing and saving
HAZARD_LABEL = {"drought": "Drought", "excess_rain": "Excess rain", "heat": "Heat"}
KIND_LABEL = {"optical": "Satellite crop health", "radar": "Radar crop evidence", "forecast": "Forecast",
              "baseline": "Historical baseline"}
INDIA_BBOX = (6.0, 68.0, 37.6, 97.5)  # rough lat/lon box of India, used only if Nominatim is down
REJECT_MESSAGE = "That point is outside India or over water. Pick a farm on land in India."


class AgentState(TypedDict, total=False):
    """Everything the agent knows during one run (BUILD_SPEC §8 'State')."""

    request: dict
    run_id: str
    today: str
    started: float
    deadline: float
    bounds: list
    place: Optional[dict]
    stage: dict
    plan: list[dict]
    plan_source: str
    pending: list[dict]
    calls: dict[str, dict]
    evidence: dict[str, dict]
    failures: list[dict]
    missing: list[str]
    notes: list[str]
    round: int
    llm_calls: int
    next_call: int
    scores: dict
    draft: Optional[dict]
    write_source: str
    rewrites: int
    validation: dict
    result: dict
    translation: Optional[dict]
    analysis_id: str
    rejected: bool
    trace: Annotated[list, operator.add]


def _remaining(state: AgentState) -> float:
    """Seconds left before the run's 45 s deadline."""
    return state["deadline"] - time.monotonic()


def _emitter() -> Emitter:
    """An event emitter bound to this graph run's live stream."""
    try:
        return Emitter(get_stream_writer())
    except RuntimeError:  # called outside a streaming run (unit tests)
        return Emitter(None)


def _new_id(state: AgentState, offset: int = 0) -> str:
    """Sequential call id: c1, c2, ..."""
    return f"c{state.get('next_call', 1) + offset}"


# ------------------------------------------------------------------ 1. check_location

async def check_location(state: AgentState) -> dict:
    """Announce the run at once (so the trace starts within 1 s), then reverse-geocode the point as the first tool
    row. Stop politely if it is outside India or over water. Work out the crop stage."""
    em = _emitter()
    req = state["request"]
    lat, lon = req["lat"], req["lon"]
    today = date.fromisoformat(state["today"])
    sowing = date.fromisoformat(req["sowing_date"]) if req.get("sowing_date") else None
    stage = stage_for(req["crop"], sowing, today)
    bounds = analysis_box(lat, lon)
    em("run_started", run_id=state["run_id"], lat=lat, lon=lon, place=None, crop=req["crop"],
       stage=stage.model_dump(), bounds=bounds, lang=req.get("lang", "en-IN"))
    em("tool_started", call_id="c0", tool="geocode", label="Finding the village, district and state", args={})
    t0 = time.perf_counter()
    notes: list[str] = []
    try:
        place = (await geocode.reverse(lat, lon)).model_dump(mode="json")
    except geocode.RejectedLocation as exc:
        em("tool_failed", call_id="c0", tool="geocode", error_code="REJECTED_LOCATION", message=exc.reason,
           will_retry=False, duration_ms=int((time.perf_counter() - t0) * 1000))
        em("error", code="REJECTED_LOCATION", message=REJECT_MESSAGE, retryable=False, detail=exc.reason)
        return {"rejected": True, "trace": em.events}
    except SourceUnavailable as exc:
        s, w, n, e = INDIA_BBOX
        if not (s <= lat <= n and w <= lon <= e):
            em("error", code="REJECTED_LOCATION", message=REJECT_MESSAGE, retryable=False)
            return {"rejected": True, "trace": em.events}
        label = geocode.coordinates_label(lat, lon)
        place = {"name": "Unnamed place", "display_name": label,
                 "source": {"name": geocode.SOURCE, "url": geocode.SOURCE_URL, "fetched_at": now_ist().isoformat(),
                            "note": "Place names unavailable right now"}}
        notes.append(f"Place names are unavailable right now; showing {label}.")
        em("tool_failed", call_id="c0", tool="geocode", error_code=exc.code, message=exc.reason, will_retry=False,
           duration_ms=int((time.perf_counter() - t0) * 1000))
        em("fallback", from_tool="geocode", to_tool=None, call_id="c0", chosen_by="rules",
           reason="Coordinates only", label=f"Place names unavailable → labelled {label}")
        return {"place": place, "stage": stage.model_dump(), "bounds": bounds, "notes": notes, "rejected": False,
                "trace": em.events}
    src = place["source"]
    em("tool_succeeded", call_id="c0", tool="geocode", duration_ms=int((time.perf_counter() - t0) * 1000),
       summary=", ".join(x for x in (place["name"], place.get("district"), place.get("state")) if x),
       place=place, source={"name": src["name"], "url": src["url"], "fetched_at": src["fetched_at"],
                            "cached": src.get("cached", False)})
    return {"place": place, "stage": stage.model_dump(), "bounds": bounds, "notes": notes, "rejected": False,
            "trace": em.events}


def route_after_location(state: AgentState) -> str:
    """End the run if the location was rejected."""
    return END if state.get("rejected") else "plan"


# ------------------------------------------------------------------ 2. plan

def _request_text(state: AgentState) -> str:
    """Describe the request for the planning prompt."""
    req, place, stage = state["request"], state["place"] or {}, state["stage"]
    return (f"Farm at {req['lat']:.4f}, {req['lon']:.4f} ({place.get('name')}, {place.get('district')}, "
            f"{place.get('state')}). Crop: {CROP_LABELS.get(req['crop'], req['crop'])}. Stage: {stage['label']}"
            f"{' (sensitive stage)' if stage.get('sensitive') else ''}. Today: {state['today']}. Plan the evidence.")


async def plan(state: AgentState) -> dict:
    """LLM proposes tool calls with reasons; code then guarantees the required set (optical, forecast, baseline)."""
    em = _emitter()
    fail = state["request"].get("fail")
    llm_calls = state.get("llm_calls", 0)
    source = "llm"
    plan_cached = False
    try:
        llm_calls += 1
        proposed, plan_cached = await llm.plan(_request_text(state), simulate_outage=fail == "llm",
                                               timeout_s=min(8.0, _remaining(state) - 30))
    except llm.LLMUnavailable as exc:
        proposed, source = [], "rules"
        em("note", level="warning", message=f"Plan generated from rules ({exc})")
    steps: list[dict] = []
    seen: set[str] = set()
    for p in proposed:
        tool = p["tool"]
        if tool not in tools.CATALOGUE or tool in seen:
            continue
        args = {**tools.DEFAULT_ARGS[tool], **{k: v for k, v in p["args"].items()
                                               if k in tools.CATALOGUE[tool]["params"]}}
        if tool == "get_optical_index":
            args["window_days"] = 30  # the 45-day window is a recovery step, not a first choice
        seen.add(tool)
        steps.append({"tool": tool, "args": args, "reason": p["reason"] or "Requested by the planner",
                      "added_by": "llm"})
    for tool in tools.REQUIRED:
        if tool not in seen:
            steps.append({"tool": tool, "args": dict(tools.DEFAULT_ARGS[tool]),
                          "reason": ("Required evidence for every analysis" if source == "llm"
                                     else _rule_reason(tool)), "added_by": "rules"})
    start = state.get("next_call", 1)
    for i, step in enumerate(steps):
        step["call_id"] = f"c{start + i}"
    em("plan", steps=[{"id": s["call_id"], "tool": s["tool"], "args": s["args"], "reason": s["reason"],
                       "added_by": s["added_by"]} for s in steps], source=source, cached=plan_cached)
    return {"plan": steps, "pending": steps, "plan_source": source, "llm_calls": llm_calls,
            "next_call": start + len(steps), "round": 0, "calls": {}, "evidence": {}, "missing": [],
            "trace": em.events}


def _rule_reason(tool: str) -> str:
    """Default one-line reasons used when the plan comes from rules."""
    return {"get_optical_index": "Crop health now vs the same weeks last year",
            "get_forecast": "16-day rain, heat and soil moisture outlook",
            "get_baseline": "20-year normal to measure how unusual this season is"}.get(tool, "")


# ------------------------------------------------------------------ 3. gather

async def gather(state: AgentState) -> dict:
    """Run the pending tool calls in parallel, streaming started/succeeded/failed events as they happen."""
    em = _emitter()
    req = state["request"]
    today = date.fromisoformat(state["today"])
    calls = dict(state.get("calls", {}))
    evidence = dict(state.get("evidence", {}))
    failures: list[dict] = []

    async def run_one(step: dict) -> None:
        """Execute one call and record its outcome."""
        cid, tool, args = step["call_id"], step["tool"], step["args"]
        em("tool_started", call_id=cid, tool=tool, label=tools.start_label(tool, args), args=args)
        t0 = time.perf_counter()
        attempt = sum(1 for c in calls.values() if c["tool"] == tool)
        calls[cid] = {"tool": tool, "args": args, "status": "running", "attempt": attempt}
        try:
            result = await tools.execute(tool, args, lat=req["lat"], lon=req["lon"], bounds=state["bounds"],
                                         today=today, fail=req.get("fail"))
        except Exception as exc:  # every failure becomes a recoverable, logged event
            ms = int((time.perf_counter() - t0) * 1000)
            code = tools.error_code(exc)
            message = exc.reason if isinstance(exc, SourceUnavailable) else f"{type(exc).__name__}: {exc}"
            options = tools.allowed_fallbacks(tool, args, code, attempt)
            will_retry = state.get("round", 0) < MAX_ROUNDS and any(o.tool for o in options)
            calls[cid].update(status="failed", error_code=code, message=message, duration_ms=ms)
            if code not in ("SIMULATED_OUTAGE", "TOO_CLOUDY", "NOT_FARMLAND"):
                tools.record(tool, False)
            failures.append({"call_id": cid, "tool": tool, "args": args, "error_code": code, "message": message,
                             "attempt": attempt,
                             "cloud_pct": exc.cloud_pct if isinstance(exc, TooCloudy) else None})
            em("tool_failed", call_id=cid, tool=tool, error_code=code, message=message, will_retry=will_retry,
               duration_ms=ms)
            return
        ms = int((time.perf_counter() - t0) * 1000)
        tools.record(tool, True)
        src = result.source
        source = {"name": src.name, "url": src.url, "fetched_at": src.fetched_at.isoformat(), "cached": src.cached,
                  "scene_date": src.scene_date.isoformat() if src.scene_date else None, "note": src.note}
        calls[cid].update(status="ok", duration_ms=ms, summary=tools.summary(tool, result), source=source)
        evidence[tools.KIND[tool]] = {"call_id": cid, "tool": tool, "args": args,
                                      "result": result.model_dump(mode="json")}
        em("tool_succeeded", call_id=cid, tool=tool, duration_ms=ms, summary=calls[cid]["summary"], source=source,
           kind=tools.KIND[tool], result=result.model_dump(mode="json", exclude={"overlays"}))

    pending = state.get("pending", [])
    budget = max(1.0, _remaining(state) - WRITE_RESERVE_S)
    tasks = {asyncio.create_task(run_one(step)): step for step in pending}
    done, not_done = await asyncio.wait(tasks, timeout=budget)
    for task in not_done:
        task.cancel()
        step = tasks[task]
        cid = step["call_id"]
        calls[cid] = {**calls.get(cid, {}), "tool": step["tool"], "args": step["args"], "status": "failed",
                      "error_code": "RUN_DEADLINE", "message": "Stopped to stay within the 45 s run limit"}
        failures.append({"call_id": cid, "tool": step["tool"], "args": step["args"], "error_code": "RUN_DEADLINE",
                         "message": "Stopped to stay within the 45 s run limit", "attempt": 0, "cloud_pct": None})
        em("tool_failed", call_id=cid, tool=step["tool"], error_code="RUN_DEADLINE",
           message="Stopped to stay within the 45 s run limit", will_retry=False)
    if not_done:
        await asyncio.gather(*not_done, return_exceptions=True)
    return {"calls": calls, "evidence": evidence, "failures": failures, "pending": [], "trace": em.events}


# ------------------------------------------------------------------ 4. check

async def check(state: AgentState) -> dict:
    """Mark each result usable or not (clear optical view, no null-only series, forecast ≥ 7 days)."""
    em = _emitter()
    evidence = dict(state["evidence"])
    failures = list(state.get("failures", []))
    notes = list(state.get("notes", []))
    if "forecast" in evidence:
        f = evidence["forecast"]["result"]
        if all(v is None for v in f["rain_series"]) or f["forecast_days"] < 7:
            failures.append(_unusable(evidence.pop("forecast"), "FORECAST_UNUSABLE", "forecast has no usable days"))
    if "optical" in evidence:
        o = evidence["optical"]["result"]
        if o["clear_fraction"] < 0.6:
            failures.append(_unusable(evidence.pop("optical"), "TOO_CLOUDY", "box not clear enough"))
        elif o.get("land_note") and o["land_note"] not in notes:
            notes.append(o["land_note"])
            em("note", level="warning", message=o["land_note"])
    if "optical" in evidence and "radar" in evidence:
        pass  # optical wins in scoring; radar stays as extra evidence
    return {"evidence": evidence, "failures": failures, "notes": notes, "trace": em.events}


def _unusable(entry: dict, code: str, message: str) -> dict:
    """Turn a stored result that failed the usability check into a failure record."""
    return {"call_id": entry["call_id"], "tool": entry["tool"], "args": entry["args"], "error_code": code,
            "message": message, "attempt": 0, "cloud_pct": None}


def route_after_check(state: AgentState) -> str:
    """Recover while there are failures, rounds left and time to spare; otherwise go score."""
    if state.get("failures") and state.get("round", 0) < MAX_ROUNDS and _remaining(state) > WRITE_RESERVE_S + 3:
        return "recover"
    return "score"


# ------------------------------------------------------------------ 5. recover

def _cause(f: dict) -> str:
    """Short human cause for the trace, e.g. 'Cloud 85%'."""
    if f["error_code"] == "TOO_CLOUDY" and f.get("cloud_pct") is not None:
        return f"Cloud {f['cloud_pct']:.0f}%"
    if f["error_code"] == "SIMULATED_OUTAGE":
        return f["message"]
    return f"{f['tool']} failed ({f['message']})"


async def recover(state: AgentState) -> dict:
    """For each failed call, choose an allowed fallback (LLM first, else the first allowed option)."""
    em = _emitter()
    fail = state["request"].get("fail")
    failures = state.get("failures", [])
    options = {f["call_id"]: tools.allowed_fallbacks(f["tool"], f["args"], f["error_code"], f["attempt"])
               for f in failures}
    llm_calls = state.get("llm_calls", 0)
    picks: dict[str, dict] = {}
    choosable = {cid: opts for cid, opts in options.items() if len(opts) > 1}
    if choosable and llm_calls < get_settings().max_llm_calls - 1:
        lines = [f"- call_id {f['call_id']}: {f['tool']}({json.dumps(f['args'])}) failed: {_cause(f)}. Allowed: "
                 + "; ".join(f"{o.id} = {o.label}" for o in options[f["call_id"]]) for f in failures
                 if f["call_id"] in choosable]
        try:
            llm_calls += 1
            picks = await llm.choose_fallbacks(
                "Failed evidence calls:\n" + "\n".join(lines), list(choosable),
                sorted({o.id for opts in choosable.values() for o in opts}), simulate_outage=fail == "llm",
                timeout_s=min(8.0, _remaining(state) - WRITE_RESERVE_S - 4))
        except llm.LLMUnavailable as exc:
            em("note", level="warning", message=f"Recovery chosen by rules ({exc})")
    pending: list[dict] = []
    missing = list(state.get("missing", []))
    next_call = state.get("next_call", 1)
    for f in failures:
        opts = options[f["call_id"]]
        pick = picks.get(f["call_id"], {})
        chosen = next((o for o in opts if o.id == pick.get("option_id")), opts[0])
        by = "llm" if pick and chosen.id == pick.get("option_id") else "rules"
        reason = pick.get("reason") if by == "llm" and pick.get("reason") else chosen.label
        if chosen.tool is None:
            kind = tools.KIND[f["tool"]]
            label = "crop evidence" if kind in ("optical", "radar") else KIND_LABEL[kind].lower()
            em("fallback", from_tool=f["tool"], to_tool=None, call_id=f["call_id"], chosen_by=by,
               reason=reason, label=f"{_cause(f)} → marking {label} as missing")
            continue
        cid = f"c{next_call}"
        next_call += 1
        pending.append({"call_id": cid, "tool": chosen.tool, "args": chosen.args, "reason": reason,
                        "added_by": by})
        em("fallback", from_tool=f["tool"], to_tool=chosen.tool, call_id=f["call_id"], new_call_id=cid,
           chosen_by=by, reason=reason, label=f"{_cause(f)} → {chosen.label.lower()}")
    return {"pending": pending, "missing": missing, "failures": [], "round": state.get("round", 0) + 1,
            "llm_calls": llm_calls, "next_call": next_call, "trace": em.events}


def route_after_recover(state: AgentState) -> str:
    """Gather again if a fallback was chosen, else go score."""
    return "gather" if state.get("pending") else "score"


# ------------------------------------------------------------------ 6. score

def _missing_sources(evidence: dict) -> list[str]:
    """Human names of the evidence kinds that are missing after recovery."""
    missing = []
    if "optical" not in evidence and "radar" not in evidence:
        missing.append("Satellite crop health")
    if "forecast" not in evidence:
        missing.append("Forecast")
    if "baseline" not in evidence:
        missing.append("Historical baseline")
    return missing


async def score(state: AgentState) -> dict:
    """Run the risk engine on whatever evidence is in, emit the risk and the map overlays."""
    em = _emitter()
    evidence = state.get("evidence", {})
    missing = _missing_sources(evidence)
    if missing:
        em("partial", missing=missing, message=_partial_message(missing))
    cid = _new_id(state)
    stage = StageInfo(**state["stage"])
    em("tool_started", call_id=cid, tool="score_risk", label="Scoring drought, excess rain and heat risk", args={})
    t0 = time.perf_counter()
    inputs = tools.build_inputs(evidence)
    fetched = now_ist()
    out = score_all(inputs, state["request"]["crop"], stage, call_id=cid, fetched_at=fetched)
    ms = int((time.perf_counter() - t0) * 1000)
    parts = [f"{HAZARD_LABEL[s.hazard]} {s.score if s.score is not None else 'n/a'}" for s in out.scores]
    em("tool_succeeded", call_id=cid, tool="score_risk", duration_ms=ms, summary=" · ".join(parts),
       source={"name": ENGINE_SOURCE, "url": "", "fetched_at": fetched.isoformat(),
               "cached": False})
    em("risk", scores=[s.model_dump(mode="json") for s in out.scores], overall_level=out.overall_level,
       confidence=out.confidence, confidence_reasons=out.confidence_reasons, headline=out.headline,
       call_id=cid)
    for kind in ("optical", "radar"):
        if kind in evidence:
            for ov in evidence[kind]["result"].get("overlays", []):
                em("overlay", **ov, source_kind=kind)
    score_fields = {f"{s.hazard}_score": s.score for s in out.scores}
    score_fields.update({k: v for k, v in out.derived.items()})
    score_fields["soil_comfort_m3m3"] = risk_rules()["drought"]["soil_comfort_m3m3"]
    return {"scores": {"call_id": cid, "fetched_at": fetched.isoformat(), "fields": score_fields,
                       "scores": [s.model_dump(mode="json") for s in out.scores],
                       "overall_level": out.overall_level, "confidence": out.confidence,
                       "confidence_reasons": out.confidence_reasons, "headline": out.headline},
            "missing": missing, "next_call": state.get("next_call", 1) + 1, "trace": em.events}


def _partial_message(missing: list[str]) -> str:
    """Banner text for a partial result."""
    if missing == ["Forecast"]:
        return "Forecast unavailable, using recent observations"
    return f"{', '.join(missing)} unavailable right now. Showing a partial result."


# ------------------------------------------------------------------ 7. write

def _evidence_for_llm(state: AgentState) -> dict[str, dict]:
    """{call_id: {field: value}} for every successful tool call plus the scoring step."""
    out = {e["call_id"]: tools.evidence_fields(tools.load_result(kind, e["result"]))
           for kind, e in state.get("evidence", {}).items()}
    sc = state["scores"]
    out[sc["call_id"]] = sc["fields"]
    return out


def _context_numbers(state: AgentState) -> list[float]:
    """Tool arguments and fixed windows that may appear in text (e.g. '16 days', '20-year')."""
    args = [v for e in state.get("evidence", {}).values() for v in e["args"].values() if isinstance(v, (int, float))]
    return [16, 30, 7, 3, 500, baseline_src.LAST_YEAR - baseline_src.FIRST_YEAR + 1, baseline_src.FIRST_YEAR,
            baseline_src.LAST_YEAR, risk_rules()["rainy_day_mm"], *args]


def _write_prompt(state: AgentState, problems: Optional[list] = None) -> str:
    """The user part of the write prompt: request context, scores and the EVIDENCE table."""
    req, place, stage, sc = state["request"], state.get("place") or {}, state["stage"], state["scores"]
    today = date.fromisoformat(state["today"])
    lines = [
        f"Place: {place.get('name')}, {place.get('district')}, {place.get('state')}. "
        f"Crop: {CROP_LABELS.get(req['crop'])}. Stage: {stage['label']}.",
        f"Today: {today.isoformat()}. Forecast window: {today.isoformat()} to {(today + timedelta(days=15)).isoformat()}.",
        f"Confidence: {sc['confidence']}" + (f" ({'; '.join(sc['confidence_reasons'])})"
                                            if sc["confidence_reasons"] else ""),
        f"Missing data: {', '.join(state.get('missing') or []) or 'none'}.",
        "Risk scores (computed by the risk engine, call " + sc["call_id"] + "):",
    ]
    for s in sc["scores"]:
        drivers = "; ".join(d["text"] for d in s["drivers"])
        lines.append(f"- {HAZARD_LABEL[s['hazard']]}: {s['score'] if s['score'] is not None else 'not enough data'}"
                     f" ({s['level'] or 'n/a'}). Drivers: {drivers or 'n/a'}")
    lines.append("EVIDENCE (call_id → fields):")
    lines.append(json.dumps(_evidence_for_llm(state), ensure_ascii=False))
    lines.append(FORMAT_NOTE)
    if problems:
        lines.append(REWRITE_NOTE.format(problems="\n".join(f"- {p['line']}: {'; '.join(p['problems'])}"
                                                           for p in problems),
                                         start=today.isoformat(), end=(today + timedelta(days=16)).isoformat()))
    return "\n".join(lines)


async def write(state: AgentState) -> dict:
    """LLM drafts the summary and 3-5 cited actions; with no LLM, rule-based template actions are used."""
    em = _emitter()
    llm_calls = state.get("llm_calls", 0)
    rewrites = state.get("rewrites", 0)
    problems = state.get("validation", {}).get("failing_lines") if rewrites else None
    if llm_calls >= get_settings().max_llm_calls or _remaining(state) < 4:
        return {"draft": None, "write_source": "rules", "trace": em.events}
    try:
        llm_calls += 1
        draft, cached = await llm.write(_write_prompt(state, problems),
                                        simulate_outage=state["request"].get("fail") == "llm",
                                        timeout_s=_remaining(state) - 3)
        if cached:
            em("note", level="info", message="Plan text reused from an identical earlier run (cached Gemini response)")
        return {"draft": draft, "write_source": "llm", "llm_calls": llm_calls, "trace": em.events}
    except llm.LLMUnavailable as exc:
        em("note", level="warning", message=f"Plan generated from rules ({exc})")
        return {"draft": None, "write_source": "rules", "llm_calls": llm_calls, "trace": em.events}


# ------------------------------------------------------------------ 8. validate

def _citation_objects(refs: list[str], state: AgentState) -> list[Citation]:
    """Turn 'c3.water_deficit_mm' strings into full Citation objects (source, value, fetch time)."""
    by_call = {e["call_id"]: (kind, e) for kind, e in state.get("evidence", {}).items()}
    sc = state["scores"]
    out = []
    for ref in refs:
        cid, _, field = str(ref).partition(".")
        if cid == sc["call_id"] and field in sc["fields"]:
            out.append(Citation(call_id=cid, source=ENGINE_SOURCE, field=field, value=sc["fields"][field],
                                fetched_at=datetime.fromisoformat(sc["fetched_at"])))
        elif cid in by_call:
            kind, e = by_call[cid]
            result = tools.load_result(kind, e["result"])
            fields = tools.evidence_fields(result)
            if field in fields:
                out.append(Citation(call_id=cid, source=result.source.name, field=field, value=fields[field],
                                    fetched_at=result.source.fetched_at))
    return out


def rules_plan(state: AgentState) -> dict:
    """Template plan built only from the risk drivers and forecast dates (used when the LLM is unavailable or
    fewer than 2 validated actions remain). Every number comes from a driver, which carries its citations."""
    today = date.fromisoformat(state["today"])
    sc = state["scores"]
    scores = [RiskScore(**s) for s in sc["scores"]]
    scored = sorted([s for s in scores if s.score is not None], key=lambda s: s.score, reverse=True)
    fc = state.get("evidence", {}).get("forecast")
    forecast = tools.load_result("forecast", fc["result"]) if fc else None
    end = today + timedelta(days=15)

    def clamp(d: date) -> date:
        """Keep a date inside today..today+15."""
        return min(max(d, today), end)

    def day_before_peak(series: list, window: int = 1) -> date:
        """The day before the highest value (or rolling sum) in the forecast series."""
        if not forecast:
            return clamp(today + timedelta(days=2))
        vals = [v or 0 for v in series]
        sums = [sum(vals[i:i + window]) for i in range(max(1, len(vals) - window + 1))]
        i = max(range(len(sums)), key=sums.__getitem__)
        return clamp(forecast.dates[i] - timedelta(days=1))

    actions: list[dict] = []
    for s in scored:
        if s.level == "low" or not s.drivers:
            continue
        d = s.drivers[0]
        if s.hazard == "drought":
            act = ("Give the field a light irrigation in the early morning or evening, and check the water reaches "
                   "the root zone")
            by = clamp(today + timedelta(days=2 if s.level == "high" else 4))
        elif s.hazard == "excess_rain":
            act = "Clear field drainage channels and hold off irrigation and spraying until the heavy rain passes"
            by = day_before_peak(forecast.rain_series if forecast else [], 3)
        else:
            act = "Irrigate lightly in the evening before the hottest days to reduce heat stress on the crop"
            by = day_before_peak(forecast.tmax_series if forecast else [])
        actions.append({"by_date": by.isoformat(), "action": act, "reason": d.text, "citations": d.citations})
    if not actions and scored:
        top = scored[0]
        d = top.drivers[0] if top.drivers else None
        actions.append({"by_date": clamp(today + timedelta(days=7)).isoformat(),
                        "action": "No urgent weather risk: continue normal field work and check the forecast again",
                        "reason": d.text if d else "All three risks are low", "citations": d.citations if d else []})
    sat = next((d for s in scores for d in s.drivers for c in d.citations
                if c.field in ("ndmi", "ndmi_last_year", "delta_vh_db", "vh_db")), None)
    if len(actions) < 2:
        actions.append({"by_date": clamp(today + timedelta(days=7)).isoformat(),
                        "action": "Walk the field and note crop condition and soil wetness in a few spots",
                        "reason": sat.text if sat else "Field checks confirm what the satellite and forecast show",
                        "citations": sat.citations if sat else []})
    actions.append({"by_date": clamp(today + timedelta(days=7)).isoformat(),
                    "action": "For any pesticide or fertiliser decision, consult your local KVK or agriculture officer",
                    "reason": "KhetKavach does not give chemical or dosage advice", "citations": []})
    if scored:
        top = scored[0]
        summary = (f"{HAZARD_LABEL[top.hazard]} risk is {top.level}, with a score of {top.score}, for the next 16 days. "
                   + (top.drivers[0].text + "." if top.drivers else ""))
    else:
        summary = "There is not enough data to score the risks right now."
    if state.get("missing"):
        summary += f" Missing data: {', '.join(state['missing']).lower()}."
    return {"summary": summary, "actions": actions[:5]}


async def validate_node(state: AgentState) -> dict:
    """Check every number in the draft against the evidence; rewrite once, then drop failing lines, then fall
    back to template actions if fewer than 2 remain. Emits `action_plan` and `validation`."""
    em = _emitter()
    today = date.fromisoformat(state["today"])
    evidence = _evidence_for_llm(state)
    context = _context_numbers(state)
    draft = state.get("draft")
    rewrites = state.get("rewrites", 0)
    if draft is not None:
        report = validate(draft, evidence, today, context)
        if report["failing_lines"] and rewrites == 0 and state.get("llm_calls", 0) < get_settings().max_llm_calls \
                and _remaining(state) > 6:
            em("validation", numbers_checked=report["numbers_checked"], numbers_rejected=report["numbers_rejected"],
               regenerated=True, failing_lines=report["failing_lines"],
               message=f"{report['numbers_rejected']} number(s) rejected → asking for a rewrite")
            return {"validation": report, "rewrites": 1, "trace": em.events}
        failing = {f["line"] for f in report["failing_lines"]}
        kept = [a for i, a in enumerate(draft.get("actions", [])) if f"action[{i}]" not in failing][:5]
        summary = draft.get("summary", "") if "summary" not in failing else ""
        source = "llm"
        actions = [{**a, "citations": _citation_objects(a.get("citations", []), state)} for a in kept]
        dropped = len(draft.get("actions", [])) - len(kept)
        if len(actions) < 2 or not summary:
            template = rules_plan(state)
            if len(actions) < 2:
                actions, source = template["actions"], "rules"
            if not summary:
                summary = template["summary"]
        message = (f"{report['numbers_checked']} numbers checked, {report['numbers_rejected']} rejected"
                   + (f", {dropped} line(s) removed" if dropped else ""))
    else:
        plan_out = rules_plan(state)
        summary, actions, source = plan_out["summary"], plan_out["actions"], "rules"
        tmp = {"summary": summary, "actions": [{**a, "citations": [f"{c.call_id}.{c.field}" for c in a["citations"]]}
                                               for a in actions]}
        report = validate(tmp, evidence, today, context)
        message = f"{report['numbers_checked']} numbers checked, {report['numbers_rejected']} rejected (rule-based plan)"
    final_actions = [Action(by_date=a["by_date"], action=a["action"], reason=a["reason"],
                            citations=a["citations"]).model_dump(mode="json") for a in actions]
    em("action_plan", summary=summary, actions=final_actions, lang="en-IN", source=source)
    em("validation", numbers_checked=report["numbers_checked"], numbers_rejected=report["numbers_rejected"],
       regenerated=rewrites > 0, failing_lines=report["failing_lines"], message=message)
    return {"validation": report, "result": {"summary": summary, "actions": final_actions, "source": source},
            "trace": em.events}


def route_after_validate(state: AgentState) -> str:
    """Go back to `write` once if a rewrite was requested, else continue."""
    return "write" if state.get("rewrites") == 1 and "result" not in state else "localise"


# ------------------------------------------------------------------ 9. localise

async def localise(state: AgentState) -> dict:
    """Translate the checked English plan when the user picked another language (Sarvam, F9)."""
    em = _emitter()
    lang = state["request"].get("lang", "en-IN")
    if lang == "en-IN":
        return {"translation": None, "trace": em.events}
    try:
        from app.sources import sarvam  # imported here so a Sarvam problem can never block startup
    except ImportError:
        em("note", level="warning", message="Translation unavailable right now. Showing English.")
        return {"translation": None, "trace": em.events}
    try:
        translated = await sarvam.translate_plan(state["result"], lang,
                                                 simulate_outage=state["request"].get("fail") == "sarvam")
        em("translation", **translated)
        return {"translation": translated, "trace": em.events}
    except sarvam.SarvamUnavailable as exc:
        em("note", level="warning", message=f"Translation unavailable right now ({exc}). Showing English.")
        return {"translation": None, "trace": em.events}


# ------------------------------------------------------------------ 10. save

async def save(state: AgentState) -> dict:
    """Store the full analysis (for share links) and emit run_completed."""
    em = _emitter()
    req, sc = state["request"], state["scores"]
    analysis_id = str(uuid.uuid4())
    duration_ms = int((time.monotonic() - state["started"]) * 1000)
    analysis = Analysis(
        id=analysis_id, created_at=now_ist(), lat=req["lat"], lon=req["lon"],
        place=Place(**state["place"]) if state.get("place") and state["place"].get("source") else None,
        crop=req["crop"], sowing_date=req.get("sowing_date"), stage=StageInfo(**state["stage"]),
        bounds=state["bounds"],
        evidence={k: {"call_id": v["call_id"], "tool": v["tool"], "args": v.get("args", {}), "result": v["result"]}
                  for k, v in state.get("evidence", {}).items()},
        scores=[RiskScore(**s) for s in sc["scores"]], overall_level=sc["overall_level"],
        confidence=sc["confidence"], confidence_reasons=sc["confidence_reasons"],
        summary=state["result"]["summary"], actions=[Action(**a) for a in state["result"]["actions"]],
        plan_source=state["result"]["source"], missing=state.get("missing", []), notes=state.get("notes", []),
    )
    payload = jsonable(analysis.model_dump(mode="json"))
    payload["headline"] = sc.get("headline")
    payload["translation"] = state.get("translation")
    payload["calls"] = state.get("calls", {})
    payload["lang"] = req.get("lang", "en-IN")
    payload["demo_fail"] = req.get("fail")
    payload["score_call"] = {"call_id": sc["call_id"], "fetched_at": sc["fetched_at"], "fields": sc["fields"],
                             "scores": sc["scores"], "confidence": sc["confidence"],
                             "confidence_reasons": sc["confidence_reasons"], "overall_level": sc["overall_level"]}
    payload["today"] = state["today"]
    payload["trace"] = [e for e in (state.get("trace") or [])]
    completed = em("run_completed", run_id=state["run_id"], analysis_id=analysis_id, duration_ms=duration_ms)
    payload["trace"].append(completed)
    stored = await cache.save_analysis(analysis_id, req["lat"], req["lon"], req["crop"], payload)
    return {"analysis_id": analysis_id, "trace": em.events, "saved_remote": stored}


# ------------------------------------------------------------------ graph

def build_graph():
    """Wire the nodes into the LangGraph state graph."""
    g = StateGraph(AgentState)
    g.add_node("check_location", check_location)
    g.add_node("plan", plan)
    g.add_node("gather", gather)
    g.add_node("check", check)
    g.add_node("recover", recover)
    g.add_node("score", score)
    g.add_node("write", write)
    g.add_node("validate", validate_node)
    g.add_node("localise", localise)
    g.add_node("save", save)
    g.add_edge(START, "check_location")
    g.add_conditional_edges("check_location", route_after_location, ["plan", END])
    g.add_edge("plan", "gather")
    g.add_edge("gather", "check")
    g.add_conditional_edges("check", route_after_check, ["recover", "score"])
    g.add_conditional_edges("recover", route_after_recover, ["gather", "score"])
    g.add_edge("score", "write")
    g.add_edge("write", "validate")
    g.add_conditional_edges("validate", route_after_validate, ["write", "localise"])
    g.add_edge("localise", "save")
    g.add_edge("save", END)
    return g.compile()


GRAPH = build_graph()


def initial_state(lat: float, lon: float, crop: str, sowing_date: Optional[date], lang: str,
                  fail: Optional[str]) -> AgentState:
    """Fresh state for one run, with the 45 s deadline starting now."""
    started = time.monotonic()
    return AgentState(
        request={"lat": lat, "lon": lon, "crop": crop, "sowing_date": sowing_date.isoformat() if sowing_date else None,
                 "lang": lang, "fail": fail},
        run_id=str(uuid.uuid4()), today=now_ist().date().isoformat(), started=started,
        deadline=started + get_settings().run_timeout_s, llm_calls=0, next_call=1, rewrites=0, trace=[])
