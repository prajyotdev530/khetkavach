"""Helpers for the Server-Sent Events stream that drives the live agent trace (BUILD_SPEC §5).

Every event is a small dict `{"event": name, "data": {...}}`. Nodes of the agent graph emit events as they
happen; the API turns them into SSE messages, and the same list is saved as the analysis trace.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable, Optional

from app.sources.common import now_ist

EVENT_NAMES = {
    "run_started", "plan", "tool_started", "tool_succeeded", "tool_failed", "fallback", "overlay", "risk",
    "action_plan", "validation", "translation", "partial", "run_completed", "error", "note",
}


def _default(value: Any) -> Any:
    """JSON encoder for dates, datetimes and Pydantic models."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def make(name: str, **data: Any) -> dict:
    """Build one event with an IST timestamp. Unknown names are a programming error."""
    if name not in EVENT_NAMES:
        raise ValueError(f"unknown event {name}")
    return {"event": name, "data": {**data, "ts": now_ist().isoformat()}}


def to_sse(event: dict) -> dict:
    """Convert an event into the dict sse-starlette sends: `event:` line plus JSON `data:`."""
    return {"event": event["event"], "data": json.dumps(event["data"], default=_default, ensure_ascii=False)}


def jsonable(value: Any) -> Any:
    """Round-trip a value through JSON so it is plain dicts/lists/strings (safe to store and stream)."""
    return json.loads(json.dumps(value, default=_default))


class Emitter:
    """Sends events to the live stream and remembers them for the saved trace (overlays are not repeated)."""

    def __init__(self, writer: Optional[Callable[[dict], None]]) -> None:
        """`writer` is LangGraph's stream writer (None when a node runs outside a stream, e.g. in tests)."""
        self.writer = writer
        self.events: list[dict] = []

    def __call__(self, name: str, **data: Any) -> dict:
        """Emit one event now and keep a trace copy (without the large overlay images)."""
        ev = make(name, **jsonable(data))
        if self.writer:
            self.writer(ev)
        if name != "overlay":
            self.events.append(ev)
        return ev
