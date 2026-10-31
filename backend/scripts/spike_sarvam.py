"""Spike: confirm the Sarvam translate, text-to-speech and speech-to-text contracts with real calls.

Run: `.venv/bin/python scripts/spike_sarvam.py` (needs SARVAM_API_KEY in ../.env).
Uses very short texts to spend well under ₹1 of credit:
1. Translates one English advisory sentence (with numbers) to Hindi and Marathi with international numerals.
2. Speaks a few characters with the chosen Bulbul v4 Flash voice for each of the 9 app languages,
   so every voice name in the app is proven valid.
3. Sends the Hindi audio it just generated back to speech-to-text with language auto-detect.
"""

import base64
import os
import struct
import time

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
KEY = os.environ.get("SARVAM_API_KEY", "")
HEAD = {"api-subscription-key": KEY}

# One voice per language, picked from the bulbul:v4-flash speaker list in Sarvam's TTS reference.
VOICES = {
    "en-IN": "simran_en_narration", "hi-IN": "ritu_hi_conversation", "mr-IN": "neha_mr_narration",
    "bn-IN": "arnab_bn_conversation", "gu-IN": "pooja_gu_conversational", "kn-IN": "chaitra_kn_narration",
    "pa-IN": "harpreet_pa_narration", "ta-IN": "vijay_ta_narration", "te-IN": "kavitha_te_narration",
}


def wav_info(raw: bytes) -> str:
    """Describe a WAV byte string: header tag, channels, sample rate and duration."""
    if raw[:4] != b"RIFF":
        return f"not RIFF (first bytes {raw[:4]!r})"
    channels, rate = struct.unpack("<HI", raw[22:28])
    bits = struct.unpack("<H", raw[34:36])[0]
    seconds = (len(raw) - 44) / (rate * channels * bits / 8)
    return f"WAV {channels}ch {rate} Hz {bits}-bit ≈{seconds:.1f}s"


def main() -> None:
    """Run the translate, TTS and STT probes and print each response's shape."""
    with httpx.Client(headers=HEAD, timeout=30) as c:
        text = "Irrigate before 6 Nov; a dry spell of 9 days is forecast and rain is 48% below normal."
        for lang in ("hi-IN", "mr-IN"):
            t0 = time.perf_counter()
            r = c.post("https://api.sarvam.ai/translate", json={
                "input": text, "source_language_code": "en-IN", "target_language_code": lang,
                "model": "sarvam-translate:v1", "numerals_format": "international"})
            print(f"== translate {lang} HTTP {r.status_code} {time.perf_counter() - t0:.2f}s keys={list(r.json())}")
            print("  ", r.json().get("translated_text"))

        hindi_audio = b""
        for lang, voice in VOICES.items():
            sample = {"hi-IN": "सिंचाई करें", "mr-IN": "पाणी द्या"}.get(lang, "Irrigate now")
            t0 = time.perf_counter()
            r = c.post("https://api.sarvam.ai/text-to-speech", json={
                "text": sample, "language_code": lang, "model": "bulbul:v4-flash",
                "speaker": voice, "pace": 0.95})
            body = r.json()
            if r.status_code == 200:
                raw = base64.b64decode(body["audios"][0])
                print(f"== tts {lang} {voice} OK {time.perf_counter() - t0:.2f}s keys={list(body)} {wav_info(raw)}")
                if lang == "hi-IN":
                    hindi_audio = raw
            else:
                print(f"== tts {lang} {voice} HTTP {r.status_code}: {body}")

        if hindi_audio:
            r = c.post("https://api.sarvam.ai/speech-to-text",
                       files={"file": ("q.wav", hindi_audio, "audio/wav")},
                       data={"model": "saaras:v4", "language_code": "unknown"})
            print(f"== stt HTTP {r.status_code}: {r.json()}")


if __name__ == "__main__":
    main()
