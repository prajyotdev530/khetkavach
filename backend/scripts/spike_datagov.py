"""Spike: check the data.gov.in district crop-production API (P1, F14) with the team key.

Run: `.venv/bin/python scripts/spike_datagov.py`. Tries the district-wise crop production resource, prints
the field names and one filtered sample (Nashik, wheat) so the yield module uses the real field names.
"""

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
KEY = os.environ.get("DATA_GOV_IN_API_KEY", "")
RESOURCE = sys.argv[1] if len(sys.argv) > 1 else "35be999b-0208-4354-b557-f6ca9a5355de"


def main() -> None:
    """Fetch one record, then a filtered query, and print the response shape."""
    base = f"https://api.data.gov.in/resource/{RESOURCE}"
    r = httpx.get(base, params={"api-key": KEY, "format": "json", "limit": 2}, timeout=75)
    print("HTTP", r.status_code)
    if r.status_code != 200:
        print("body:", r.text[:300])
        return
    data = r.json()
    print("keys:", sorted(data.keys()))
    print("title:", data.get("title"), "| total:", data.get("total"), "| updated:", data.get("updated_date"))
    print("fields:", [(f.get("id"), f.get("name"), f.get("type")) for f in data.get("field", [])])
    print("sample:", data.get("records", [])[:2])
    r = httpx.get(base, params={"api-key": KEY, "format": "json", "limit": 5,
                                "filters[district_name]": "NASHIK", "filters[crop]": "Wheat"}, timeout=75)
    print("filtered HTTP", r.status_code, "count", r.json().get("count"), r.json().get("records", [])[:3])


if __name__ == "__main__":
    main()
