"""Tests for the Sarvam helpers (number check after translation, speech text, WAV joining) and a live
translate + voice round trip through the API (marked live; spends well under ₹1 of credit, then cached)."""

import base64
import struct

import pytest

from app.sources import sarvam


def test_numbers_must_survive_translation():
    """Same 0-9 numbers pass; a dropped number or native digits fail."""
    assert sarvam.numbers_survived("Deficit 64.3 mm over 16 days", "16 दिनों में 64.3 मिमी की कमी")
    assert not sarvam.numbers_survived("Deficit 64.3 mm over 16 days", "16 दिनों में कमी")
    assert not sarvam.numbers_survived("Rain 48% below", "बारिश ४८% कम")
    assert sarvam.numbers_survived("1,500 m", "1500 मीटर")


def test_speech_text_reads_summary_and_top_three_actions():
    """The voice text is the summary plus the first three actions, under 1,500 characters."""
    actions = [{"action": f"Action {i}"} for i in range(5)]
    text = sarvam.speech_text("Summary here", actions)
    assert text == "Summary here. Action 0. Action 1. Action 2."
    assert len(sarvam.speech_text("x. " * 900, actions)) <= sarvam.SPEAK_MAX_CHARS


def _wav(n: int) -> bytes:
    """A minimal mono 16-bit WAV with n zero samples (for testing the joiner only)."""
    pcm = b"\x00\x00" * n
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 22050, 44100, 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE" + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm


def test_join_wavs_fixes_sizes():
    """Joined WAV has both clips' samples and correct RIFF/data sizes."""
    joined = sarvam.join_wavs([_wav(10), _wav(5)])
    assert struct.unpack("<I", joined[40:44])[0] == 30
    assert struct.unpack("<I", joined[4:8])[0] == 36 + 30


@pytest.mark.live
async def test_translate_and_tts_live():
    """A real Hindi translation keeps the numbers, and Bulbul returns a playable WAV."""
    plan = {"summary": "Drought risk is high, with a score of 78.",
            "actions": [{"by_date": "2026-11-02", "action": "Irrigate the field lightly",
                         "reason": "Evaporation will exceed rain by 64.3 mm over the next 16 days", "citations": []}]}
    tr = await sarvam.translate_plan(plan, "hi-IN")
    assert tr["lang"] == "hi-IN" and not tr["summary_english_fallback"]
    assert "78" in tr["summary"]
    audio = await sarvam.speak(sarvam.speech_text(tr["summary"], tr["actions"]), "hi-IN")
    raw = base64.b64decode(audio["audio_base64"])
    assert raw[:4] == b"RIFF" and len(raw) > 10_000
