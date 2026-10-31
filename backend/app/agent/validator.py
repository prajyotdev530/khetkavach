"""Citation validator: rejects any number in the plan that is not in the tool outputs it cites (F8, BUILD_SPEC §8).

How it works:
1. Pull every number out of the summary and each action with a regular expression (integers, decimals,
   negatives, numbers followed by a unit or %). Product names like "Sentinel-2" and calendar dates are not numbers.
2. Each number must match a value in the evidence fields that line cites: absolute difference ≤ 0.5 or relative
   difference ≤ 2% (the sign is ignored, since "48% below normal" describes an anomaly of −48). The summary has no
   citation list, so its numbers may match any evidence value. Tool arguments (e.g. "16 days") also count.
3. Every citation must point to a real call_id and field, and every by_date must fall within today..today+16.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Iterable

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_NAME_WITH_DIGITS = re.compile(r"\b[A-Za-z]+[\-]?\d+[A-Za-z\d]*\b")         # Sentinel-2, ERA5, B04
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTHS})[a-z]*\.?(?:,?\s+((?:19|20)\d{{2}})\b)?", re.I)
_MONTH_DAY = re.compile(rf"\b({MONTHS})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+((?:19|20)\d{{2}})\b)?", re.I)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
_REF_IN_TEXT = re.compile(r"\bc\d+\.[A-Za-z_]\w*")
MONTH_NUM = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                         "nov", "dec"], start=1)}
FORECAST_WINDOW_DAYS = 16


def _month(token: str) -> int:
    """Month number from a month name or abbreviation."""
    return MONTH_NUM[token.lower()[:3]]


def extract(text: str, today: date) -> tuple[list[float], list[date]]:
    """Return (numbers, dates) mentioned in a sentence. Dates are taken out first so '6 Nov' is not the number 6."""
    t = text.replace("−", "-").replace("–", "-")
    t = _THOUSANDS.sub("", t)
    dates: list[date] = []

    def take_iso(m: re.Match) -> str:
        """Record an ISO date and blank it out."""
        try:
            dates.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return m.group(0)
        return " "

    def take_day_month(m: re.Match) -> str:
        """Record a '6 Nov (2026)' date and blank it out."""
        try:
            dates.append(date(int(m.group(3) or today.year), _month(m.group(2)), int(m.group(1))))
        except ValueError:
            return m.group(0)
        return " "

    def take_month_day(m: re.Match) -> str:
        """Record a 'Nov 6 (2026)' date and blank it out."""
        try:
            dates.append(date(int(m.group(3) or today.year), _month(m.group(1)), int(m.group(2))))
        except ValueError:
            return m.group(0)
        return " "

    t = _ISO_DATE.sub(take_iso, t)
    t = _DAY_MONTH.sub(take_day_month, t)
    t = _MONTH_DAY.sub(take_month_day, t)
    t = _NAME_WITH_DIGITS.sub(" ", t)
    return [float(n) for n in _NUMBER.findall(t)], dates


def _numbers_in(value: Any) -> Iterable[float]:
    """Every number inside a field value (walking lists and dicts, e.g. the daily forecast table)."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _numbers_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _numbers_in(v)


def _dates_in(value: Any) -> Iterable[date]:
    """Every ISO date string inside a field value."""
    if isinstance(value, str) and _ISO_DATE.fullmatch(value):
        yield date.fromisoformat(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _dates_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _dates_in(v)


def matches(number: float, allowed: Iterable[float]) -> bool:
    """True if `number` equals some allowed value within 0.5 absolute or 2% relative (sign ignored)."""
    n = abs(number)
    for a in allowed:
        a = abs(a)
        if abs(n - a) <= 0.5 or (a and abs(n - a) / a <= 0.02):
            return True
    return False


def validate(draft: dict, evidence: dict[str, dict], today: date,
             context_numbers: Iterable[float] = ()) -> dict:
    """Check a drafted plan against the evidence.

    `draft` = {"summary": str, "actions": [{"by_date", "action", "reason", "citations": ["c3.field", ...]}]}.
    `evidence` = {call_id: {field: value}}. `context_numbers` are tool arguments such as the 16-day window.
    Returns {"numbers_checked", "numbers_rejected", "failing_lines": [{"line", "problems"}]}.
    """
    context = list(context_numbers)
    all_numbers = context + [n for fields in evidence.values() for n in _numbers_in(fields)]
    all_dates = {d for fields in evidence.values() for d in _dates_in(fields)}
    window_end = today + timedelta(days=FORECAST_WINDOW_DAYS)
    checked = rejected = 0
    failing: list[dict] = []

    def check_text(text: str, allowed_numbers: list[float], problems: list[str]) -> None:
        """Validate the numbers and dates inside one piece of text."""
        nonlocal checked, rejected
        for ref in _REF_IN_TEXT.findall(text):
            problems.append(f"'{ref}' is a citation written inside the text; write the number instead")
        numbers, dates = extract(_REF_IN_TEXT.sub(" ", text), today)
        for n in numbers:
            checked += 1
            if not matches(n, allowed_numbers):
                rejected += 1
                problems.append(f"number {n:g} is not in the cited evidence")
        for d in dates:
            if d not in all_dates and not (today <= d <= window_end):
                problems.append(f"date {d.isoformat()} is outside the forecast window and not in the evidence")

    summary_problems: list[str] = []
    check_text(draft.get("summary", ""), all_numbers, summary_problems)
    if summary_problems:
        failing.append({"line": "summary", "problems": summary_problems})

    for i, action in enumerate(draft.get("actions", [])):
        problems: list[str] = []
        cited: list[float] = list(context)
        for ref in action.get("citations", []):
            call_id, _, field = str(ref).partition(".")
            if call_id not in evidence or field not in evidence[call_id]:
                problems.append(f"citation {ref} does not exist")
                continue
            cited.extend(_numbers_in(evidence[call_id][field]))
        try:
            by = date.fromisoformat(str(action.get("by_date")))
            if not (today <= by <= window_end):
                problems.append(f"by_date {by.isoformat()} is outside {today.isoformat()}..{window_end.isoformat()}")
        except ValueError:
            problems.append(f"by_date {action.get('by_date')!r} is not a YYYY-MM-DD date")
        check_text(f"{action.get('action', '')} {action.get('reason', '')}", cited, problems)
        if problems:
            failing.append({"line": f"action[{i}]", "problems": problems})
    return {"numbers_checked": checked, "numbers_rejected": rejected, "failing_lines": failing}
