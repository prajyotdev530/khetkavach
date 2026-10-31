"""Thin wrapper around the Gemini API (google-genai SDK) for the agent's plan, recover and write steps.

Function calling and JSON-schema output are separate calls (BUILD_SPEC §8). Each call has a 15 s timeout and
counts against a budget of 4 LLM calls per run. Any failure raises LLMUnavailable, and the graph then uses its
rule-based fallback, so a rate limit or outage never breaks a run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Awaitable, Callable, Optional

from google import genai
from google.genai import types

from app.agent.prompts import ASK_SCHEMA, ASK_SYSTEM, PLAN_SYSTEM, RECOVER_SYSTEM, WRITE_SCHEMA, WRITE_SYSTEM
from app import cache
from app.agent.tools import CATALOGUE
from app.config import get_settings
from app.sources.common import now_ist

LLM_CACHE_TTL_S = 3600  # same lifetime as the forecast cache: identical evidence gives an identical prompt


class LLMUnavailable(Exception):
    """The LLM could not be used for this step (no key, budget spent, timeout, rate limit or simulated outage)."""


_client: Optional[genai.Client] = None


def client() -> genai.Client:
    """Create the Gemini client once per process (the key comes from GEMINI_API_KEY)."""
    global _client
    key = get_settings().gemini_api_key
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY is not set")
    if _client is None:
        _client = genai.Client(api_key=key)
    return _client


def _base_config() -> dict:
    """Settings shared by every call: 15 s timeout and low thinking for speed."""
    return {"http_options": types.HttpOptions(timeout=int(get_settings().llm_timeout_s * 1000)),
            "thinking_config": types.ThinkingConfig(thinking_level="low"),
            "temperature": 0.2}


async def _generate(contents: str, config: types.GenerateContentConfig, simulate_outage: bool,
                    timeout_s: Optional[float] = None) -> Any:
    """Make one Gemini call with the timeout (15 s, or less if the run is near its deadline); translate every
    failure into LLMUnavailable."""
    if simulate_outage:
        raise LLMUnavailable("Simulated outage: llm (demo control)")
    timeout = min(timeout_s or get_settings().llm_timeout_s, get_settings().llm_timeout_s)
    if timeout < 2:
        raise LLMUnavailable("not enough time left in the run for an LLM call")
    try:
        return await asyncio.wait_for(
            client().aio.models.generate_content(model=get_settings().gemini_model, contents=contents, config=config),
            timeout=timeout)
    except LLMUnavailable:
        raise
    except asyncio.TimeoutError as exc:
        raise LLMUnavailable(f"Gemini timed out after {timeout:.0f} s") from exc
    except Exception as exc:  # google.genai.errors.APIError (429 rate limit, 5xx) or network errors
        code = getattr(exc, "code", None)
        raise LLMUnavailable(f"Gemini error {code or type(exc).__name__}: {str(exc)[:160]}") from exc


async def _memo(kind: str, text: str, simulate_outage: bool, fn: Callable[[], Awaitable[Any]]) -> tuple[Any, bool]:
    """Reuse Gemini's real earlier answer to an identical prompt (sha256 of model + step + prompt) for 1 hour.
    Returns (value, from_cache). A simulated LLM outage always bypasses the cache."""
    if simulate_outage:
        raise LLMUnavailable("Simulated outage: llm (demo control)")
    key = "llm:" + hashlib.sha256(f"{get_settings().gemini_model}\x1f{kind}\x1f{text}".encode()).hexdigest()
    hit = await cache.get(key)
    if hit is not None:
        return hit.value["out"], True
    out = await fn()
    await cache.put(key, {"out": out}, "Gemini", now_ist(), LLM_CACHE_TTL_S)
    return out, False


def _tool_declarations() -> list[types.Tool]:
    """Function declarations for the evidence tools; every tool also takes a required `reason`."""
    decls = []
    for name, spec in CATALOGUE.items():
        props = {**spec["params"], "reason": {"type": "string", "description": "One line: why this evidence"}}
        decls.append(types.FunctionDeclaration(
            name=name, description=spec["description"],
            parameters_json_schema={"type": "object", "properties": props,
                                    "required": list(spec["params"]) + ["reason"]}))
    return [types.Tool(function_declarations=decls)]


async def plan(request_text: str, simulate_outage: bool = False,
               timeout_s: Optional[float] = None) -> tuple[list[dict], bool]:
    """Ask the model which tools to call. Returns ([{"tool", "args", "reason"}], from_cache)."""
    return await _memo("plan", request_text, simulate_outage, lambda: _plan(request_text, timeout_s))


async def _plan(request_text: str, timeout_s: Optional[float]) -> list[dict]:
    """The uncached planning call."""
    simulate_outage = False
    config = types.GenerateContentConfig(
        system_instruction=PLAN_SYSTEM, tools=_tool_declarations(),
        tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True), **_base_config())
    resp = await _generate(request_text, config, simulate_outage, timeout_s)
    calls = []
    for fc in resp.function_calls or []:
        args = dict(fc.args or {})
        reason = str(args.pop("reason", "")).strip()
        calls.append({"tool": fc.name, "args": args, "reason": reason})
    if not calls:
        raise LLMUnavailable("Gemini returned no tool calls")
    return calls


async def choose_fallbacks(failures_text: str, call_ids: list[str], option_ids: list[str],
                           simulate_outage: bool = False, timeout_s: Optional[float] = None) -> dict[str, dict]:
    """Ask the model to pick one allowed fallback per failed call. Returns {call_id: {"option_id", "reason"}}."""
    decl = types.FunctionDeclaration(
        name="choose_fallback", description="Pick one allowed fallback option for one failed tool call.",
        parameters_json_schema={"type": "object", "properties": {
            "call_id": {"type": "string", "enum": call_ids},
            "option_id": {"type": "string", "enum": option_ids},
            "reason": {"type": "string"}}, "required": ["call_id", "option_id", "reason"]})
    config = types.GenerateContentConfig(
        system_instruction=RECOVER_SYSTEM, tools=[types.Tool(function_declarations=[decl])],
        tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True), **_base_config())
    resp = await _generate(failures_text, config, simulate_outage, timeout_s)
    picks: dict[str, dict] = {}
    for fc in resp.function_calls or []:
        args = dict(fc.args or {})
        if args.get("call_id"):
            picks[str(args["call_id"])] = {"option_id": str(args.get("option_id", "")),
                                           "reason": str(args.get("reason", "")).strip()}
    return picks


async def write(prompt_text: str, simulate_outage: bool = False,
                timeout_s: Optional[float] = None) -> tuple[dict, bool]:
    """Ask the model for the summary and 3-5 cited actions as JSON matching WRITE_SCHEMA. Returns (draft, cached)."""
    return await _memo("write", prompt_text, simulate_outage, lambda: _write(prompt_text, timeout_s))


async def _write(prompt_text: str, timeout_s: Optional[float]) -> dict:
    """The uncached writing call."""
    simulate_outage = False
    config = types.GenerateContentConfig(
        system_instruction=WRITE_SYSTEM, response_mime_type="application/json",
        response_json_schema=WRITE_SCHEMA,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True), **_base_config())
    resp = await _generate(prompt_text, config, simulate_outage, timeout_s)
    try:
        draft = json.loads(resp.text or "")
    except (ValueError, TypeError) as exc:
        raise LLMUnavailable(f"Gemini returned invalid JSON: {exc}") from exc
    if not isinstance(draft, dict) or not isinstance(draft.get("actions"), list):
        raise LLMUnavailable("Gemini JSON did not match the plan schema")
    return draft


async def answer(prompt_text: str, timeout_s: Optional[float] = None) -> dict:
    """Answer a farmer's question from one analysis's evidence: {"answer", "citations"} (JSON schema output)."""
    config = types.GenerateContentConfig(
        system_instruction=ASK_SYSTEM, response_mime_type="application/json", response_json_schema=ASK_SCHEMA,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True), **_base_config())
    resp = await _generate(prompt_text, config, False, timeout_s)
    try:
        out = json.loads(resp.text or "")
    except (ValueError, TypeError) as exc:
        raise LLMUnavailable(f"Gemini returned invalid JSON: {exc}") from exc
    if not isinstance(out, dict) or not isinstance(out.get("answer"), str):
        raise LLMUnavailable("Gemini JSON did not match the answer schema")
    return out
