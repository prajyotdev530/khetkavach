"""App settings read from environment variables (and `.env` when running locally), plus the risk rulebook.

Keeping every setting in one place makes it easy to see what the app needs to run and which numbers drive
the risk scores. Secrets are never hard-coded; they come from `.env` locally or platform secrets in deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
REPO_DIR = BACKEND_DIR.parent

# Local development: load the repo-level .env (and a backend/.env if someone puts it there).
load_dotenv(REPO_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")

VERSION = "1.0.0"


def _bool(name: str, default: bool = False) -> bool:
    """Read a true/false environment variable such as DEMO_CONTROLS=true."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _user_agent() -> str:
    """Nominatim User-Agent from env. Nominatim blocks placeholder contacts (e.g. example.com), so a template value
    that was never filled in is replaced by a plain app identifier instead of getting every request denied."""
    raw = os.getenv("NOMINATIM_USER_AGENT", "").strip()
    if not raw or "example.com" in raw or "your-team-email" in raw:
        return "KhetKavach/1.0 (Forge26 hackathon)"
    return raw


@dataclass(frozen=True)
class Settings:
    """All runtime settings in one immutable object."""

    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    sarvam_api_key: str = field(default_factory=lambda: os.getenv("SARVAM_API_KEY", ""))
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", "").rstrip("/"))
    supabase_key: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))
    nominatim_user_agent: str = field(default_factory=lambda: _user_agent())
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()))
    demo_controls: bool = field(default_factory=lambda: _bool("DEMO_CONTROLS", False))
    data_gov_in_api_key: str = field(default_factory=lambda: os.getenv("DATA_GOV_IN_API_KEY", ""))

    # Timeouts and budgets from BUILD_SPEC §6, §8 and §11.
    http_timeout_s: float = 8.0
    satellite_timeout_s: float = 25.0
    llm_timeout_s: float = 15.0
    run_timeout_s: float = 45.0
    max_llm_calls: int = 4

    @property
    def supabase_enabled(self) -> bool:
        """True when both Supabase settings are present, so the shared cache and share links can be used."""
        return bool(self.supabase_url and self.supabase_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the settings, built once per process."""
    return Settings()


@lru_cache(maxsize=1)
def risk_rules() -> dict:
    """Load `risk.yaml`, the documented thresholds and weights used by the risk engine."""
    with open(APP_DIR / "risk.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
