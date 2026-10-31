"""Cache of real API responses (with their original fetch time), plus saved analyses and translated media.

Two layers (BUILD_SPEC §11):
1. An in-process dictionary, so repeat requests on one server are instant.
2. Supabase Postgres (tables `cache`, `analyses`, `media` from `backend/sql/schema.sql`), shared across restarts.
   It is reached through Supabase's REST API (PostgREST) with httpx, which keeps every call async.

The cache never invents or alters data: it stores exactly what a provider returned and when. Callers mark
cache hits as "(cached)" so nothing old is shown as just fetched.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

import httpx

from app.config import get_settings
from app.sources.common import now_ist

log = logging.getLogger("khetkavach.cache")

HOUR = 3600
DAY = 24 * HOUR
TTL_PLACE = 30 * DAY
TTL_SAT_NOW = DAY
TTL_SAT_LAST_YEAR = 30 * DAY
TTL_FORECAST = HOUR
TTL_BASELINE = 30 * DAY
PERMANENT = None


@dataclass
class CacheHit:
    """A cached value with the time the provider originally returned it."""

    value: Any
    source: str
    fetched_at: datetime


_memory: dict[str, tuple[CacheHit, Optional[float]]] = {}


def _headers() -> dict[str, str]:
    """Supabase REST headers using the backend-only service-role key."""
    key = get_settings().supabase_key
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _rest(table: str) -> str:
    """URL of a Supabase table's REST endpoint."""
    return f"{get_settings().supabase_url}/rest/v1/{table}"


async def get(key: str) -> Optional[CacheHit]:
    """Return a fresh cached value for `key`, or None. Checks memory first, then Supabase."""
    entry = _memory.get(key)
    if entry:
        hit, expires = entry
        if expires is None or expires > time.time():
            return hit
        _memory.pop(key, None)
    if not get_settings().supabase_enabled:
        return None
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(_rest("cache"), headers=_headers(), params={
                "key": f"eq.{key}", "select": "value,source,fetched_at,expires_at"})
        rows = resp.json() if resp.status_code == 200 else []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("cache read failed for %s: %s", key, exc)
        return None
    if not rows:
        return None
    row = rows[0]
    expires_at = datetime.fromisoformat(row["expires_at"]) if row.get("expires_at") else None
    if expires_at and expires_at <= now_ist():
        return None
    hit = CacheHit(row["value"], row["source"], datetime.fromisoformat(row["fetched_at"]))
    _memory[key] = (hit, expires_at.timestamp() if expires_at else None)
    return hit


_background: set[asyncio.Task] = set()


async def put(key: str, value: Any, source: str, fetched_at: datetime, ttl_s: Optional[int]) -> None:
    """Store a real response under `key` for `ttl_s` seconds (None = permanent). The memory copy is immediate;
    the Supabase copy is written in the background so a run never waits for it. Failures are logged, not raised."""
    expires = fetched_at + timedelta(seconds=ttl_s) if ttl_s else None
    _memory[key] = (CacheHit(value, source, fetched_at), expires.timestamp() if expires else None)
    if not get_settings().supabase_enabled:
        return
    row = {"key": key, "value": value, "source": source, "fetched_at": fetched_at.isoformat(),
           "expires_at": expires.isoformat() if expires else None}
    task = asyncio.create_task(_write_row(key, row))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _write_row(key: str, row: dict) -> None:
    """Upsert one cache row into Supabase."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(_rest("cache"), json=row, headers={
                **_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"})
        if resp.status_code >= 300:
            log.warning("cache write failed for %s: HTTP %s %s", key, resp.status_code, resp.text[:200])
    except httpx.HTTPError as exc:
        log.warning("cache write failed for %s: %s", key, exc)


async def cached(
    key: str,
    ttl_s: Optional[int],
    source: str,
    fetch: Callable[[], Awaitable[dict]],
) -> tuple[dict, bool]:
    """Return (value, from_cache). On a miss, call `fetch()` (which must return a JSON-able dict that includes
    `source.fetched_at`) and store the result."""
    hit = await get(key)
    if hit is not None:
        return hit.value, True
    value = await fetch()
    fetched_at = datetime.fromisoformat(value["source"]["fetched_at"]) if isinstance(
        value.get("source", {}).get("fetched_at"), str) else now_ist()
    await put(key, value, source, fetched_at, ttl_s)
    return value, False


def clear_memory() -> None:
    """Empty the in-process cache (used by tests and the demo 'fresh run' path)."""
    _memory.clear()


# ---------- saved analyses (share links, F15) and media (translations, audio) ----------

_analyses: dict[str, dict] = {}
_media: dict[str, dict] = {}


async def save_analysis(analysis_id: str, lat: float, lon: float, crop: str, payload: dict) -> bool:
    """Save a finished analysis so `/api/analysis/{id}` can read it back. Returns True if stored in Supabase."""
    _analyses[analysis_id] = payload
    if not get_settings().supabase_enabled:
        return False
    row = {"id": analysis_id, "created_at": payload.get("created_at"), "lat": lat, "lon": lon,
           "crop": crop, "payload": payload}
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(_rest("analyses"), json=row, headers={
                **_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"})
        if resp.status_code >= 300:
            log.warning("analysis save failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        return True
    except httpx.HTTPError as exc:
        log.warning("analysis save failed: %s", exc)
        return False


async def load_analysis(analysis_id: str) -> Optional[dict]:
    """Read a saved analysis by id from memory or Supabase."""
    if analysis_id in _analyses:
        return _analyses[analysis_id]
    if not get_settings().supabase_enabled:
        return None
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(_rest("analyses"), headers=_headers(), params={
                "id": f"eq.{analysis_id}", "select": "payload"})
        rows = resp.json() if resp.status_code == 200 else []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("analysis load failed: %s", exc)
        return None
    if not rows:
        return None
    _analyses[analysis_id] = rows[0]["payload"]
    return rows[0]["payload"]


async def get_media(key: str) -> Optional[dict]:
    """Read a cached translation or audio clip (keyed by sha256 of model + language + voice + text)."""
    if key in _media:
        return _media[key]
    if not get_settings().supabase_enabled:
        return None
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(_rest("media"), headers=_headers(), params={
                "key": f"eq.{key}", "select": "lang,kind,data,created_at"})
        rows = resp.json() if resp.status_code == 200 else []
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("media load failed: %s", exc)
        return None
    if not rows:
        return None
    _media[key] = rows[0]
    return rows[0]


async def put_media(key: str, lang: str, kind: str, data: str) -> None:
    """Store a translation (kind='translation', JSON text) or audio (kind='audio', base64 WAV) permanently."""
    row = {"key": key, "lang": lang, "kind": kind, "data": data, "created_at": now_ist().isoformat()}
    _media[key] = row
    if not get_settings().supabase_enabled:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_rest("media"), json=row, headers={
                **_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"})
        if resp.status_code >= 300:
            log.warning("media save failed: HTTP %s %s", resp.status_code, resp.text[:200])
    except httpx.HTTPError as exc:
        log.warning("media save failed: %s", exc)


async def health() -> str:
    """'ok' if Supabase answers (or is not configured: memory-only mode is 'degraded'), else 'degraded'."""
    if not get_settings().supabase_enabled:
        return "degraded"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(_rest("cache"), headers=_headers(), params={"select": "key", "limit": 1})
        return "ok" if resp.status_code == 200 else "degraded"
    except httpx.HTTPError:
        return "degraded"
