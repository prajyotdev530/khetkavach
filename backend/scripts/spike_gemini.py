"""Spike: confirm the Gemini free-tier model supports the two call styles the agent needs.

Run: `.venv/bin/python scripts/spike_gemini.py [model]` (needs GEMINI_API_KEY in ../.env).
1. Lists the Flash models this key can use.
2. A function-calling call (the agent's `plan` step): the model must return tool calls, not text.
3. A JSON-schema call (the agent's `write` step): the model must return JSON matching the schema.
Prints latency for each so we can pick a model that fits the 15 s per-call budget.
"""

import json
import os
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

TOOLS = [types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_forecast",
        description="16-day daily rain, max temperature, evapotranspiration and soil moisture for a point.",
        parameters_json_schema={"type": "object", "properties": {
            "lat": {"type": "number"}, "lon": {"type": "number"}}, "required": ["lat", "lon"]},
    ),
    types.FunctionDeclaration(
        name="get_optical_index",
        description="Sentinel-2 NDVI/NDMI now and last year for a 500 m box.",
        parameters_json_schema={"type": "object", "properties": {
            "lat": {"type": "number"}, "lon": {"type": "number"},
            "window_days": {"type": "integer"}}, "required": ["lat", "lon", "window_days"]},
    ),
])]

SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "actions": {"type": "array", "items": {"type": "object", "properties": {
        "by_date": {"type": "string"}, "action": {"type": "string"}, "reason": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}}},
        "required": ["by_date", "action", "reason", "citations"]}}},
    "required": ["summary", "actions"]}


def main() -> None:
    """Run the three probes against the chosen model and print what came back."""
    model = sys.argv[1] if len(sys.argv) > 1 else os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    print("== models visible to this key (flash only):")
    for m in client.models.list():
        if "flash" in m.name:
            print("  ", m.name, getattr(m, "supported_actions", None))

    base = dict(http_options=types.HttpOptions(timeout=15_000),
                thinking_config=types.ThinkingConfig(thinking_level="low"))

    print(f"\n== function calling with {model}")
    t0 = time.perf_counter()
    resp = client.models.generate_content(
        model=model,
        contents="Plan the evidence needed to assess drought risk for a wheat farm at 20.0, 73.79. Call the tools.",
        config=types.GenerateContentConfig(
            tools=TOOLS,
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            **base),
    )
    print(f"  {time.perf_counter() - t0:.2f}s; function_calls:")
    for fc in resp.function_calls or []:
        print("   ", fc.name, dict(fc.args))
    print("  usage:", resp.usage_metadata)

    print(f"\n== JSON schema output with {model}")
    t0 = time.perf_counter()
    resp = client.models.generate_content(
        model=model,
        contents="EVIDENCE: call c1 (forecast): rain_next16_mm=8.6, longest_dry_run_days=11. "
                 "Write a short summary and 3 actions for a wheat farmer; cite as c1.field. Today is 2026-10-31.",
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_json_schema=SCHEMA, **base),
    )
    print(f"  {time.perf_counter() - t0:.2f}s")
    print(json.dumps(json.loads(resp.text), indent=2)[:1500])


if __name__ == "__main__":
    main()
