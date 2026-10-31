"""API and event-stream tests (BUILD_SPEC §12): input validation, the event order of a run, valid JSON in every
event, and that every demo control (satellite, forecast, baseline, llm, sarvam) gives a partial result, not a crash.

Runs marked `live` call the real data providers through the full agent.
"""

import json
import os

import httpx
import pytest

os.environ.setdefault("DEMO_CONTROLS", "true")

from app import cache  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

FARM = {"lat": 20.0, "lon": 73.79, "crop": "wheat"}


async def stream_events(params: dict) -> list[tuple[str, dict]]:
    """Call /api/analyze through the ASGI app and parse the SSE stream into (event, data) pairs."""
    transport = httpx.ASGITransport(app=app)
    events: list[tuple[str, dict]] = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=90) as client:
        async with client.stream("GET", "/api/analyze", params=params) as resp:
            assert resp.status_code == 200
            name = None
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:") and name:
                    events.append((name, json.loads(line[5:].strip())))  # every event must be valid JSON
                    name = None
    return events


async def get(path: str, **params) -> httpx.Response:
    """GET a JSON endpoint through the ASGI app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, params=params)


async def test_invalid_input_returns_422_with_message():
    """Out-of-range latitude, unknown crop and a future sowing date give 422 with a clear message."""
    r = await get("/api/analyze", lat=95, lon=73, crop="rice")
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"
    assert "lat" in r.json()["message"] and "crop" in r.json()["message"]
    r = await get("/api/analyze", lat=20, lon=73, sowing_date="2099-01-01")
    assert r.status_code == 422 and "future" in r.json()["message"]


async def test_health_shape():
    """/health returns status, version and a per-source ok/degraded map."""
    body = (await get("/health")).json()
    assert body["status"] == "ok" and body["version"]
    assert set(body["sources"].values()) <= {"ok", "degraded"}


async def test_rejected_location_stops_before_any_data_call():
    """An ocean click ends with a REJECTED_LOCATION error right after the place lookup; no data tool runs
    (uses live Nominatim)."""
    events = await stream_events({"lat": 18.5, "lon": 70.0, "crop": "wheat"})
    assert [e for e, _ in events] == ["run_started", "tool_started", "tool_failed", "error"]
    assert all(d.get("tool") in (None, "geocode") for _, d in events)
    assert events[-1][1]["code"] == "REJECTED_LOCATION" and events[-1][1]["retryable"] is False


@pytest.mark.live
async def test_full_run_event_order():
    """A full run emits run_started first and run_completed last, with risk, plan and validation in between."""
    cache.clear_memory()
    events = await stream_events(FARM)
    names = [e for e, _ in events]
    assert names[0] == "run_started" and names[-1] == "run_completed"
    for required in ("plan", "tool_started", "tool_succeeded", "risk", "action_plan", "validation"):
        assert required in names
    plan = next(d for e, d in events if e == "action_plan")
    assert 2 <= len(plan["actions"]) <= 5
    completed = events[-1][1]
    saved = (await get(f"/api/analysis/{completed['analysis_id']}")).json()
    assert saved["id"] == completed["analysis_id"] and saved["scores"]


@pytest.mark.live
@pytest.mark.parametrize("fail", ["satellite", "forecast", "baseline", "llm", "sarvam"])
async def test_demo_controls_give_partial_result_not_crash(fail):
    """Each simulated outage still ends in run_completed, labelled honestly in the trace."""
    assert get_settings().demo_controls
    events = await stream_events({**FARM, "fail": fail, "lang": "hi-IN" if fail == "sarvam" else "en-IN"})
    names = [e for e, _ in events]
    assert names[0] == "run_started" and names[-1] == "run_completed"
    if fail in ("satellite", "forecast", "baseline"):
        assert "partial" in names
        failed = [d for e, d in events if e == "tool_failed"]
        assert any("Simulated outage" in d["message"] for d in failed)
    if fail == "llm":
        assert next(d for e, d in events if e == "plan")["source"] == "rules"
    if fail == "sarvam":
        assert not any(e == "translation" for e in names)
