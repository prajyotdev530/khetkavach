"""Repository hygiene checks from the P0 acceptance list (BUILD_SPEC §12): no fixture JSON, no random-number
calls used for data, and no API-key-shaped strings in the app source."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = [ROOT / "backend" / "app", ROOT / "frontend" / "src"]
CONFIG_JSON = {"package.json", "package-lock.json", "tsconfig.json", "vercel.json"}


def _files():
    """Every source file in the app folders."""
    for d in SOURCE_DIRS:
        yield from (p for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def test_no_fixture_json():
    """No JSON data files anywhere in the app or tests (only build config JSON at the project roots)."""
    found = [p for p in ROOT.rglob("*.json") if "node_modules" not in p.parts and ".venv" not in str(p)
             and p.name not in CONFIG_JSON and "dist" not in p.parts]
    assert found == [], found


def test_no_random_values():
    """No random-number generators in the app code."""
    pattern = re.compile(r"\bimport random\b|\brandom\.\w+\(|Math\.random|np\.random|faker", re.I)
    hits = [str(p) for p in _files() if pattern.search(p.read_text(errors="ignore"))]
    assert hits == [], hits


def test_no_key_shaped_strings():
    """No Supabase/Sarvam/Gemini/Hugging Face key patterns in the app source."""
    pattern = re.compile(r"sb_secret_[A-Za-z0-9]|sk_[a-z0-9]{6,}_[A-Za-z0-9]{8,}|AIza[0-9A-Za-z_-]{20,}|hf_[A-Za-z0-9]{20,}")
    hits = [str(p) for p in _files() if pattern.search(p.read_text(errors="ignore"))]
    assert hits == [], hits
