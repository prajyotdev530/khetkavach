"""KhetKavach API (FastAPI): the streaming analysis endpoint, village search, saved analyses, translation/voice
and a health check (BUILD_SPEC §5).

All external calls happen here on the backend, so no API key ever reaches the browser. Every error is returned as
`{code, message, retryable}`, never as a stack trace.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app import cache
from app.agent import graph as agent_graph
from app.agent import tools
from app.config import VERSION, get_settings
from app.events import make, to_sse
from app.sources import geocode, sarvam
from app.sources.common import SourceUnavailable, today_ist
from app.sources.satellite_optical import catalog

log = logging.getLogger("khetkavach")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# The 9 languages with both text and voice in Bulbul v4 Flash (BUILD_SPEC §9), named in their own script.
LANGUAGES = {
    "en-IN": "English", "hi-IN": "हिन्दी", "mr-IN": "मराठी", "bn-IN": "বাংলা", "gu-IN": "ગુજરાતી",
    "kn-IN": "ಕನ್ನಡ", "pa-IN": "ਪੰਜਾਬੀ", "ta-IN": "தமிழ்", "te-IN": "తెలుగు",
}
CROPS = ("wheat", "mustard", "gram", "unknown")
FAIL_OPTIONS = ("satellite", "forecast", "baseline", "llm", "sarvam")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Warm up at start: open the Planetary Computer catalogue so the first click is not slower than the rest."""
    try:
        await asyncio.wait_for(asyncio.to_thread(catalog), timeout=15)
    except Exception as exc:  # the app still starts; the first satellite call will retry
        log.warning("STAC warm-up failed: %s", exc)
    yield


app = FastAPI(title="KhetKavach API", version=VERSION, lifespan=lifespan)
_origins = list(get_settings().allowed_origins)
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])


def problem(status: int, code: str, message: str, retryable: bool, **extra) -> JSONResponse:
    """A JSON error in the app's standard shape."""
    return JSONResponse(status_code=status, content={"code": code, "message": message, "retryable": retryable,
                                                     **extra})


@app.exception_handler(RequestValidationError)
async def on_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Invalid input (lat/lon out of range, unknown crop...) → 422 with a plain message per field."""
    fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    message = "; ".join(f"{f['field']}: {f['message']}" for f in fields) or "Invalid input"
    return problem(422, "INVALID_INPUT", message, False, fields=fields)


@app.exception_handler(HTTPException)
async def on_http_error(_: Request, exc: HTTPException) -> JSONResponse:
    """Our own HTTP errors carry a dict detail with code/message/retryable."""
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "ERROR", "message": str(exc.detail),
                                                               "retryable": False}
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.exception_handler(Exception)
async def on_unexpected(_: Request, exc: Exception) -> JSONResponse:
    """Anything unexpected → 500 with a calm message (details only in the server log)."""
    log.exception("unhandled error: %s", exc)
    return problem(500, "INTERNAL", "Something went wrong on our side. Please try again.", True)


def bad_input(message: str, field: str) -> HTTPException:
    """422 for a rule FastAPI cannot express in the type (e.g. a future sowing date)."""
    return HTTPException(422, {"code": "INVALID_INPUT", "message": message, "retryable": False,
                               "fields": [{"field": field, "message": message}]})


# ------------------------------------------------------------------ routes

@app.get("/health")
async def health() -> dict:
    """Liveness + per-source status: 'ok' or 'degraded' (last call failed, or a key is not configured)."""
    s = get_settings()
    sources = {
        "sentinel_2": tools.STATUS.get("get_optical_index", "ok"),
        "sentinel_1": tools.STATUS.get("get_radar_index", "ok"),
        "open_meteo": tools.STATUS.get("get_forecast", "ok"),
        "baseline": tools.STATUS.get("get_baseline", "ok"),
        "gemini": "ok" if s.gemini_api_key else "degraded",
        "sarvam": "ok" if s.sarvam_api_key else "degraded",
        "supabase": await cache.health(),
    }
    return {"status": "ok", "version": VERSION, "sources": sources}


@app.get("/api/meta")
async def meta() -> dict:
    """Static choices for the UI: languages (in their own script), crops, and whether demo controls are on."""
    return {"languages": [{"code": k, "name": v} for k, v in LANGUAGES.items()], "crops": list(CROPS),
            "demo_controls": get_settings().demo_controls, "fail_options": list(FAIL_OPTIONS), "version": VERSION}


@app.get("/api/search")
async def search(q: str = Query(..., min_length=3, max_length=100)) -> dict:
    """Up to 5 places in India for a village/town name (Nominatim, cached, ≤ 1 request/second)."""
    try:
        hits = await geocode.search(q)
    except SourceUnavailable as exc:
        raise HTTPException(503, {"code": "SEARCH_UNAVAILABLE", "message": "Place search is unavailable right now. "
                                  "You can still click the map.", "retryable": True, "detail": exc.reason})
    return {"results": [h.model_dump() for h in hits]}


@app.get("/api/analyze")
async def analyze(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    crop: Literal["wheat", "mustard", "gram", "unknown"] = "unknown",
    sowing_date: Optional[date] = None,
    lang: str = "en-IN",
    fail: Optional[str] = None,
):
    """Run the agent for one farm and stream every step as Server-Sent Events (keep-alive every 15 s)."""
    if sowing_date and sowing_date > today_ist():
        raise bad_input("Sowing date cannot be in the future.", "sowing_date")
    if lang not in LANGUAGES:
        raise bad_input(f"Unsupported language {lang}.", "lang")
    if fail is not None:
        if not get_settings().demo_controls:
            raise bad_input("Demo controls are disabled on this server.", "fail")
        if fail not in FAIL_OPTIONS:
            raise bad_input(f"fail must be one of {', '.join(FAIL_OPTIONS)}.", "fail")
    state = agent_graph.initial_state(lat, lon, crop, sowing_date, lang, fail)
    return EventSourceResponse(run_stream(state), ping=15, headers={"Cache-Control": "no-cache",
                                                                    "X-Accel-Buffering": "no"})


async def run_stream(state: dict):
    """Stream the graph's live events. Guarantees the last event is `run_completed` or `error`."""
    terminal = False
    try:
        async with asyncio.timeout(get_settings().run_timeout_s + 10):
            async for mode, chunk in agent_graph.GRAPH.astream(state, stream_mode=["custom", "values"]):
                if mode != "custom":
                    continue
                if chunk["event"] in ("run_completed", "error"):
                    terminal = True
                yield to_sse(chunk)
    except TimeoutError:
        yield to_sse(make("error", code="RUN_TIMEOUT", message="The analysis took too long. Please retry.",
                          retryable=True))
        return
    except asyncio.CancelledError:  # the browser closed the stream (e.g. user clicked another farm)
        raise
    except Exception as exc:
        log.exception("run failed: %s", exc)
        yield to_sse(make("error", code="INTERNAL", message="Something went wrong on our side. Please retry.",
                          retryable=True))
        return
    if not terminal:
        yield to_sse(make("error", code="INTERNAL", message="The analysis ended unexpectedly. Please retry.",
                          retryable=True))


@app.get("/api/analysis/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    """A saved analysis for the read-only share page."""
    payload = await cache.load_analysis(analysis_id)
    if payload is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "This analysis link was not found.",
                                  "retryable": False})
    return payload


class MediaRequest(BaseModel):
    """Body of /api/translate and /api/tts: which saved analysis, in which language."""

    analysis_id: str
    lang: str


async def _analysis_or_404(analysis_id: str) -> dict:
    """Load a saved analysis or raise a 404 in the standard error shape."""
    payload = await cache.load_analysis(analysis_id)
    if payload is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "This analysis was not found.", "retryable": False})
    return payload


async def _plan_in(payload: dict, lang: str) -> dict:
    """The checked English plan, or its translation (cached) for another language."""
    plan = {"summary": payload["summary"], "actions": payload["actions"]}
    if lang == "en-IN":
        return {"lang": "en-IN", **plan, "summary_english_fallback": False}
    return await sarvam.translate_plan(plan, lang, simulate_outage=payload.get("demo_fail") == "sarvam")


@app.post("/api/translate")
async def translate(body: MediaRequest) -> dict:
    """The plan and summary of a saved analysis in another language (Sarvam-Translate, cached)."""
    if body.lang not in LANGUAGES:
        raise bad_input(f"Unsupported language {body.lang}.", "lang")
    payload = await _analysis_or_404(body.analysis_id)
    try:
        return await _plan_in(payload, body.lang)
    except sarvam.SarvamUnavailable as exc:
        raise HTTPException(503, {"code": "TRANSLATION_UNAVAILABLE", "message": "Translation unavailable right now",
                                  "retryable": True, "detail": str(exc)})


@app.post("/api/tts")
async def tts(body: MediaRequest) -> dict:
    """Spoken summary + top 3 actions as WAV (Bulbul v4 Flash, cached): {audio_base64, mime, chars, voice}."""
    if body.lang not in LANGUAGES:
        raise bad_input(f"Unsupported language {body.lang}.", "lang")
    payload = await _analysis_or_404(body.analysis_id)
    try:
        plan = await _plan_in(payload, body.lang)
        text = sarvam.speech_text(plan["summary"], plan["actions"])
        audio = await sarvam.speak(text, body.lang, simulate_outage=payload.get("demo_fail") == "sarvam")
    except sarvam.SarvamUnavailable as exc:
        raise HTTPException(503, {"code": "VOICE_UNAVAILABLE", "message": "Voice unavailable right now",
                                  "retryable": True, "detail": str(exc)})
    return {**audio, "lang": body.lang}


# ------------------------------------------------------------------ P1: batch view (F13) and questions (F11)

class BatchPoint(BaseModel):
    """One farm in a batch request."""

    lat: float
    lon: float
    label: Optional[str] = None


class BatchRequest(BaseModel):
    """Body of /api/batch: a crop and 1-20 points."""

    crop: Literal["wheat", "mustard", "gram", "unknown"] = "unknown"
    points: list[BatchPoint]


@app.post("/api/batch")
async def batch(body: BatchRequest):
    """Quick risk for up to 20 farms, streamed as SSE: one `batch_item` per point (3 at a time), then `batch_done`."""
    from app.agent.extras import assess_point

    if not 1 <= len(body.points) <= 20:
        raise bad_input("Send between 1 and 20 points.", "points")
    for i, p in enumerate(body.points):
        if not (-90 <= p.lat <= 90 and -180 <= p.lon <= 180):
            raise bad_input(f"Point {i + 1} has an invalid latitude/longitude.", f"points.{i}")

    async def stream():
        """Run points with a concurrency of 3 and stream each result as soon as it is ready."""
        sem = asyncio.Semaphore(3)
        t0 = asyncio.get_running_loop().time()

        async def one(i: int, p: BatchPoint) -> dict:
            """Assess one point under the concurrency limit; never raises."""
            async with sem:
                try:
                    return await assess_point(i, p.lat, p.lon, body.crop, p.label)
                except Exception as exc:  # one bad point must not stop the batch
                    log.exception("batch point failed: %s", exc)
                    return {"index": i, "label": p.label, "lat": p.lat, "lon": p.lon, "status": "error",
                            "message": "Could not analyse this point"}

        tasks = [asyncio.create_task(one(i, p)) for i, p in enumerate(body.points)]
        for fut in asyncio.as_completed(tasks):
            yield to_sse({"event": "batch_item", "data": await fut})
        yield to_sse({"event": "batch_done", "data": {"count": len(tasks),
                                                      "duration_ms": int((asyncio.get_running_loop().time() - t0) * 1000)}})

    return EventSourceResponse(stream(), ping=15, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/ask")
async def ask(request: Request) -> dict:
    """Answer a question about one saved analysis, grounded only in its tool outputs.

    JSON body `{analysis_id, question, lang}`, or multipart with `file` (≤ 30 s of audio, transcribed by Saaras with
    language auto-detect), `analysis_id` and `lang`. The answer comes back in `lang` with citations.
    """
    from app.agent.extras import answer_question

    ctype = request.headers.get("content-type", "")
    detected = None
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        analysis_id, lang, upload = str(form.get("analysis_id", "")), str(form.get("lang", "en-IN")), form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise bad_input("Attach an audio file.", "file")
        audio = await upload.read()
        if len(audio) > 3_000_000:
            raise bad_input("Audio is too long; keep questions under 30 seconds.", "file")
        try:
            heard = await sarvam.transcribe(audio, upload.filename or "question.webm",
                                            upload.content_type or "audio/webm")
        except sarvam.SarvamUnavailable as exc:
            raise HTTPException(503, {"code": "STT_UNAVAILABLE", "message": "Voice input unavailable right now. "
                                      "Please type your question.", "retryable": True, "detail": str(exc)})
        question, detected = heard["transcript"].strip(), heard.get("language_code")
    else:
        body = await request.json()
        analysis_id, lang, question = str(body.get("analysis_id", "")), str(body.get("lang", "en-IN")), \
            str(body.get("question", "")).strip()
    if lang not in LANGUAGES:
        raise bad_input(f"Unsupported language {lang}.", "lang")
    if not question:
        raise bad_input("Please ask a question (we could not hear one).", "question")
    payload = await _analysis_or_404(analysis_id)
    if "score_call" not in payload:
        raise HTTPException(409, {"code": "ANALYSIS_TOO_OLD", "message": "Please run the analysis again to ask "
                                  "questions about it.", "retryable": False})
    source_lang = detected if detected in LANGUAGES else lang
    try:
        question_en = await sarvam.translate_text(question, "en-IN", source=source_lang) \
            if source_lang != "en-IN" else question
    except sarvam.SarvamUnavailable:
        question_en = question
    result = await answer_question(payload, question_en)
    answer_en, answer = result["answer"], result["answer"]
    if lang != "en-IN":
        try:
            translated = await sarvam.translate_text(answer_en, lang)
            answer = translated if sarvam.numbers_survived(answer_en, translated) else answer_en
        except sarvam.SarvamUnavailable:
            answer = answer_en
    return {"question": question, "question_en": question_en, "detected_lang": detected, "answer": answer,
            "answer_en": answer_en, "lang": lang, "citations": result["citations"], "source": result["source"],
            "english_fallback": lang != "en-IN" and answer == answer_en}
