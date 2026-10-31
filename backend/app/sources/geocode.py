"""Place names from Nominatim (OpenStreetMap): reverse geocoding for a clicked farm, and village search (F1).

Nominatim's usage policy allows at most 1 request per second, needs an identifying User-Agent, and requires
results to be cached; this module does all three. A point with no address (sea) or outside India is rejected.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from app import cache
from app.config import get_settings
from app.models import Place, SearchHit, SourceRef
from app.sources.common import SourceUnavailable, now_ist

BASE = "https://nominatim.openstreetmap.org"
SOURCE = "OpenStreetMap Nominatim"
SOURCE_URL = "https://nominatim.openstreetmap.org/"
NAME_KEYS = ("village", "hamlet", "town", "suburb", "city_district", "city", "municipality", "county")

_locks: dict[int, asyncio.Lock] = {}
_last_call = 0.0


class RejectedLocation(Exception):
    """The point is outside India or over water, so no analysis should run."""

    def __init__(self, reason: str) -> None:
        """Keep a short technical reason; the user-facing message is fixed by the API layer."""
        super().__init__(reason)
        self.reason = reason


def _lock() -> asyncio.Lock:
    """One lock per event loop, so the 1 request/second rule holds even with many parallel analyses."""
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _locks:
        _locks[loop_id] = asyncio.Lock()
    return _locks[loop_id]


async def _nominatim(path: str, params: dict) -> httpx.Response:
    """Call Nominatim politely: wait so calls are at least 1 s apart; on a 429, wait 1 s and retry once."""
    global _last_call
    headers = {"User-Agent": get_settings().nominatim_user_agent}
    async with _lock():
        for attempt in range(2):
            wait = 1.0 - (time.monotonic() - _last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(timeout=get_settings().http_timeout_s) as client:
                    resp = await client.get(f"{BASE}{path}", params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                _last_call = time.monotonic()
                raise SourceUnavailable(SOURCE, type(exc).__name__) from exc
            _last_call = time.monotonic()
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(1.0)
                continue
            if resp.status_code != 200:
                raise SourceUnavailable(SOURCE, f"HTTP {resp.status_code}")
            return resp
    raise SourceUnavailable(SOURCE, "rate limited")


def coordinates_label(lat: float, lon: float) -> str:
    """Format a point as e.g. '20.00°N, 73.79°E' for when no place name is available."""
    return f"{abs(lat):.2f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.2f}°{'E' if lon >= 0 else 'W'}"


def _place_name(address: dict) -> Optional[str]:
    """Pick the most local name in a Nominatim address (village before town before district)."""
    for key in NAME_KEYS:
        if address.get(key):
            return address[key]
    return None


async def reverse(lat: float, lon: float) -> Place:
    """Return the village/district/state for a point, or raise RejectedLocation if it is not on land in India.

    Raises SourceUnavailable if Nominatim itself is down (the agent then labels the place by coordinates).
    """
    key = f"geo:rev:{lat:.3f},{lon:.3f}"

    async def fetch() -> dict:
        """Fetch the reverse-geocode response from Nominatim and keep the raw address."""
        resp = await _nominatim("/reverse", {"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 14,
                                             "addressdetails": 1, "accept-language": "en"})
        data = resp.json()
        return {"address": data.get("address"), "display_name": data.get("display_name"),
                "error": data.get("error"),
                "source": {"name": SOURCE, "url": SOURCE_URL, "fetched_at": now_ist().isoformat()}}

    value, from_cache = await cache.cached(key, cache.TTL_PLACE, SOURCE, fetch)
    address = value.get("address") or {}
    if not address:
        raise RejectedLocation("no address (sea or uninhabited)")
    if address.get("country_code") != "in":
        raise RejectedLocation(f"country_code={address.get('country_code')}")
    source = SourceRef(**value["source"], cached=from_cache)
    return Place(
        name=_place_name(address) or coordinates_label(lat, lon),
        district=address.get("state_district") or address.get("county"),
        state=address.get("state"),
        country_code=address.get("country_code"),
        display_name=value.get("display_name"),
        source=source,
    )


async def search(q: str) -> list[SearchHit]:
    """Search places in India by name; returns up to 5 hits with district and state (cached 30 days)."""
    q = q.strip()
    key = f"geo:search:{q.lower()}"

    async def fetch() -> dict:
        """Query Nominatim search restricted to India."""
        resp = await _nominatim("/search", {"q": q, "countrycodes": "in", "format": "jsonv2", "limit": 5,
                                            "addressdetails": 1, "accept-language": "en"})
        return {"results": resp.json(),
                "source": {"name": SOURCE, "url": SOURCE_URL, "fetched_at": now_ist().isoformat()}}

    value, _ = await cache.cached(key, cache.TTL_PLACE, SOURCE, fetch)
    hits = []
    for item in value["results"]:
        address = item.get("address") or {}
        hits.append(SearchHit(
            name=item.get("name") or _place_name(address) or item.get("display_name", "").split(",")[0],
            district=address.get("state_district") or address.get("county"),
            state=address.get("state"),
            lat=float(item["lat"]), lon=float(item["lon"]),
        ))
    return hits
