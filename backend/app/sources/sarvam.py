"""Sarvam AI: translation, text-to-speech and speech-to-text in Indian languages (F9, F11; BUILD_SPEC §9).

The agent always writes and validates in English first; this module then translates the checked text and reads
it aloud. Contracts verified live (backend/scripts/spike_sarvam.py, 2026-10-31):
- Translate: POST /translate, model `sarvam-translate:v1`, max 2,000 characters, `numerals_format=international`.
- Text-to-speech: POST /text-to-speech, model `bulbul:v4-flash`, `text` ≤ 2,500 characters, base64 WAV in `audios`.
- Speech-to-text: POST /speech-to-text (multipart `file`), model `saaras:v4`, `language_code=unknown` auto-detects.
Every result is cached permanently by sha256(model + language + voice + text), so demo repeats cost nothing.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import struct
from typing import Optional

import httpx

from app import cache
from app.config import get_settings

BASE = "https://api.sarvam.ai"
TRANSLATE_MODEL = "sarvam-translate:v1"
TTS_MODEL = "bulbul:v4-flash"
STT_MODEL = "saaras:v4"
TRANSLATE_MAX_CHARS = 2000
TTS_MAX_CHARS = 2500
SPEAK_MAX_CHARS = 1500
PACE = 0.95
# One default voice per language, from the bulbul:v4-flash speaker list; each was proven valid by the spike.
VOICES = {
    "en-IN": "simran_en_narration", "hi-IN": "ritu_hi_conversation", "mr-IN": "neha_mr_narration",
    "bn-IN": "arnab_bn_conversation", "gu-IN": "pooja_gu_conversational", "kn-IN": "chaitra_kn_narration",
    "pa-IN": "harpreet_pa_narration", "ta-IN": "vijay_ta_narration", "te-IN": "kavitha_te_narration",
}
_DIGITS = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_THOUSANDS = re.compile(r"(?<=[0-9]),(?=[0-9]{3}\b)")


class SarvamUnavailable(Exception):
    """Sarvam could not be used (no key, out of credit, rate limit, outage or simulated outage)."""


def _key(*parts: str) -> str:
    """Cache key: sha256 of model + language + voice + text."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _headers() -> dict[str, str]:
    """Auth header for every Sarvam call."""
    key = get_settings().sarvam_api_key
    if not key:
        raise SarvamUnavailable("SARVAM_API_KEY is not set")
    return {"api-subscription-key": key}


async def _post(path: str, *, json_body: Optional[dict] = None, files=None, data=None, timeout: float = 20.0) -> dict:
    """POST to Sarvam with one retry on 429/5xx; 402 (no credit) and 403 (bad key) fail at once."""
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{BASE}{path}", headers=_headers(), json=json_body, files=files, data=data)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == 0:
                await asyncio.sleep(0.8)
                continue
            raise SarvamUnavailable(f"network error: {type(exc).__name__}") from exc
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503) and attempt == 0:
            await asyncio.sleep(1.0)
            continue
        reason = {402: "out of credit", 403: "invalid API key", 429: "rate limited"}.get(resp.status_code,
                                                                                       f"HTTP {resp.status_code}")
        raise SarvamUnavailable(reason)
    raise SarvamUnavailable("unavailable")


def numbers_in(text: str) -> list[str]:
    """All 0-9 numbers in a text, as strings, sorted. Native-script digits are deliberately not counted, so a
    number converted to native digits shows up as a mismatch."""
    return sorted(_DIGITS.findall(_THOUSANDS.sub("", text)))


def numbers_survived(english: str, translated: str) -> bool:
    """True if the translation contains exactly the same numbers as the English text."""
    return numbers_in(english) == numbers_in(translated)


async def translate_text(text: str, lang: str, source: str = "en-IN") -> str:
    """Translate one text (≤ 2,000 characters) from `source` into `lang`, using the permanent cache."""
    if not text.strip() or lang == source:
        return text
    if len(text) > TRANSLATE_MAX_CHARS:
        text = text[:TRANSLATE_MAX_CHARS]
    key = _key(TRANSLATE_MODEL, f"{source}>{lang}", "", text)
    hit = await cache.get_media(key)
    if hit:
        return hit["data"]
    body = await _post("/translate", json_body={
        "input": text, "source_language_code": source, "target_language_code": lang,
        "model": TRANSLATE_MODEL, "numerals_format": "international"})
    translated = body.get("translated_text") or ""
    if not translated:
        raise SarvamUnavailable("empty translation")
    await cache.put_media(key, lang, "translation", translated)
    return translated


async def translate_plan(plan: dict, lang: str, simulate_outage: bool = False) -> dict:
    """Translate the summary and each action/reason as separate items so the structure survives.

    Any line whose numbers change in translation is kept in English and flagged `english_fallback`.
    Returns {"lang", "summary", "summary_english_fallback", "actions": [...]}.
    """
    if simulate_outage:
        raise SarvamUnavailable("Simulated outage: sarvam (demo control)")
    texts = [plan["summary"]] + [t for a in plan["actions"] for t in (a["action"], a["reason"])]
    sem = asyncio.Semaphore(4)

    async def one(t: str) -> str:
        """Translate one item with limited concurrency (Sarvam allows 60 requests/minute)."""
        async with sem:
            return await translate_text(t, lang)

    out = await asyncio.gather(*(one(t) for t in texts))
    summary_ok = numbers_survived(plan["summary"], out[0])
    actions = []
    for i, a in enumerate(plan["actions"]):
        act_t, reason_t = out[1 + 2 * i], out[2 + 2 * i]
        ok = numbers_survived(a["action"], act_t) and numbers_survived(a["reason"], reason_t)
        actions.append({**a, "action": act_t if ok else a["action"], "reason": reason_t if ok else a["reason"],
                        "lang": lang if ok else "en-IN", "english_fallback": not ok})
    return {"lang": lang, "summary": out[0] if summary_ok else plan["summary"],
            "summary_english_fallback": not summary_ok, "actions": actions}


def speech_text(summary: str, actions: list[dict]) -> str:
    """What the voice reads: the summary plus the top 3 actions, at most 1,500 characters (cut at a sentence)."""
    parts = [summary.strip()] + [a["action"].strip() for a in actions[:3]]
    text = " ".join(p if p.endswith((".", "।", "?", "!")) else p + "." for p in parts if p)
    if len(text) <= SPEAK_MAX_CHARS:
        return text
    cut = text[:SPEAK_MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("। "))
    return cut[:end + 1] if end > 200 else cut


def _chunks(text: str, limit: int = TTS_MAX_CHARS) -> list[str]:
    """Split text at sentence ends into pieces under the per-request character limit."""
    if len(text) <= limit:
        return [text]
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.।!?])\s+", text):
        if len(current) + len(sentence) + 1 > limit and current:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def join_wavs(wavs: list[bytes]) -> bytes:
    """Concatenate PCM WAV clips with the same format into one WAV (rewrites the RIFF/data sizes)."""
    if len(wavs) == 1:
        return wavs[0]
    header, pcm = wavs[0][:44], b"".join(w[44:] for w in wavs)
    header = header[:4] + struct.pack("<I", 36 + len(pcm)) + header[8:40] + struct.pack("<I", len(pcm))
    return header + pcm


async def speak(text: str, lang: str, simulate_outage: bool = False) -> dict:
    """Text-to-speech with Bulbul v4 Flash. Returns {audio_base64, mime, chars, voice, cached}."""
    if simulate_outage:
        raise SarvamUnavailable("Simulated outage: sarvam (demo control)")
    voice = VOICES.get(lang)
    if not voice:
        raise SarvamUnavailable(f"no voice for {lang}")
    key = _key(TTS_MODEL, lang, voice, text)
    hit = await cache.get_media(key)
    if hit:
        return {"audio_base64": hit["data"], "mime": "audio/wav", "chars": len(text), "voice": voice, "cached": True}
    clips = []
    for piece in _chunks(text):
        body = await _post("/text-to-speech", json_body={
            "text": piece, "language_code": lang, "model": TTS_MODEL, "speaker": voice, "pace": PACE}, timeout=30)
        audios = body.get("audios") or []
        if not audios:
            raise SarvamUnavailable("no audio returned")
        clips.append(base64.b64decode(audios[0]))
    audio_b64 = base64.b64encode(join_wavs(clips)).decode("ascii")
    await cache.put_media(key, lang, "audio", audio_b64)
    return {"audio_base64": audio_b64, "mime": "audio/wav", "chars": len(text), "voice": voice, "cached": False}


async def transcribe(audio: bytes, filename: str, content_type: str) -> dict:
    """Speech-to-text with Saaras v4 and language auto-detect (≤ 30 s of audio). Returns {transcript, language_code}."""
    body = await _post("/speech-to-text", files={"file": (filename, audio, content_type)},
                       data={"model": STT_MODEL, "language_code": "unknown"}, timeout=40)
    return {"transcript": body.get("transcript", ""), "language_code": body.get("language_code"),
            "language_probability": body.get("language_probability")}


def dumps(value: dict) -> str:
    """JSON text for storing a structured translation in the media cache."""
    return json.dumps(value, ensure_ascii=False)
