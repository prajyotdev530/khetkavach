"""Shared helpers for every external data source: time in IST, the farm box, errors and the HTTP retry policy.

BUILD_SPEC §6 shared rules: async httpx; 8 s timeout per HTTP call; 2 retries with 0.5 s and 1.5 s backoff on a
timeout, 429 or 5xx; on final failure raise `SourceUnavailable`, which the agent turns into a fallback.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.config import get_settings

IST = timezone(timedelta(hours=5, minutes=30), "IST")
RETRY_BACKOFF_S = (0.5, 1.5)
RETRY_STATUS = {429, 500, 502, 503, 504}
METRES_PER_DEG_LAT = 111_320.0
BOX_HALF_SIDE_M = 250.0


def now_ist() -> datetime:
    """Current time with the Indian Standard Time offset (all timestamps are shown in IST)."""
    return datetime.now(IST)


def today_ist() -> date:
    """Today's date in India, which defines the forecast and baseline windows."""
    return now_ist().date()


def analysis_box(lat: float, lon: float, half_side_m: float = BOX_HALF_SIDE_M) -> list[list[float]]:
    """Return the 500 m analysis square as Leaflet bounds [[south, west], [north, east]] (BUILD_SPEC §4).

    Half-side offsets: 250 / 111,320 degrees of latitude and 250 / (111,320 × cos(lat)) degrees of longitude.
    """
    dlat = half_side_m / METRES_PER_DEG_LAT
    dlon = half_side_m / (METRES_PER_DEG_LAT * math.cos(math.radians(lat)))
    return [[lat - dlat, lon - dlon], [lat + dlat, lon + dlon]]


def bounds_to_bbox(bounds: list[list[float]]) -> list[float]:
    """Convert Leaflet bounds to a STAC bbox [west, south, east, north]."""
    (south, west), (north, east) = bounds
    return [west, south, east, north]


class SourceUnavailable(Exception):
    """A data source failed after its retries; the agent decides the fallback."""

    def __init__(self, source: str, reason: str, code: str = "SOURCE_UNAVAILABLE") -> None:
        """Store which source failed, a human reason and a short machine code."""
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason
        self.code = code


class TooCloudy(SourceUnavailable):
    """No Sentinel-2 scene had a clear enough view of the farm box; triggers the radar fallback (F3)."""

    def __init__(self, source: str, reason: str, cloud_pct: Optional[float] = None) -> None:
        """Record the cloud percentage of the best scene so the trace can say e.g. 'Cloud 85%'."""
        super().__init__(source, reason, code="TOO_CLOUDY")
        self.cloud_pct = cloud_pct


class NotFarmland(SourceUnavailable):
    """The farm box is mostly water, so crop-health indices do not apply."""

    def __init__(self, source: str, reason: str) -> None:
        """Mark the failure with a NOT_FARMLAND code."""
        super().__init__(source, reason, code="NOT_FARMLAND")


async def get_json(
    url: str,
    params: dict[str, Any],
    source: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout_s: Optional[float] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Any:
    """GET a JSON document with the shared timeout and retry policy, or raise SourceUnavailable.

    Retries twice (after 0.5 s and 1.5 s) on timeouts, connection errors, 429 and 5xx. Other HTTP errors fail at
    once because retrying would not help (e.g. a 400 for a bad parameter).
    """
    timeout = timeout_s or get_settings().http_timeout_s
    own = client is None
    client = client or httpx.AsyncClient(timeout=timeout, headers=headers)
    last_reason = "unknown error"
    try:
        for attempt in range(len(RETRY_BACKOFF_S) + 1):
            try:
                resp = await client.get(url, params=params, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    return resp.json()
                last_reason = f"HTTP {resp.status_code}"
                if resp.status_code not in RETRY_STATUS:
                    break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_reason = f"{type(exc).__name__}"
            except ValueError as exc:  # invalid JSON
                last_reason = f"invalid JSON: {exc}"
                break
            if attempt < len(RETRY_BACKOFF_S):
                await asyncio.sleep(RETRY_BACKOFF_S[attempt])
        raise SourceUnavailable(source, last_reason)
    finally:
        if own:
            await client.aclose()


def round_or_none(value: Optional[float], ndigits: int = 2) -> Optional[float]:
    """Round a number for display, keeping None (missing) as None."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(float(value), ndigits)
