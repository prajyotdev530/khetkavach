"""Spike: reverse-geocode and search with Nominatim (OpenStreetMap) and print the address fields.

Run: `.venv/bin/python scripts/spike_nominatim.py`. Uses NOMINATIM_USER_AGENT from the environment.
Checks a farm near Nashik, a point in the Arabian Sea and a point in Pakistan, then a village search.
Sleeps 1.1 s between calls to respect the 1 request/second policy.
"""

import json
import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
UA = os.getenv("NOMINATIM_USER_AGENT") or "KhetKavach/1.0 (Forge26 hackathon spike)"
BASE = "https://nominatim.openstreetmap.org"


def reverse(client: httpx.Client, lat: float, lon: float) -> None:
    """Reverse-geocode one point at zoom 14 and print the parts of the address the app uses."""
    r = client.get(f"{BASE}/reverse", params={
        "format": "jsonv2", "lat": lat, "lon": lon, "zoom": 14, "addressdetails": 1, "accept-language": "en"})
    data = r.json()
    print(f"\n== reverse {lat},{lon} HTTP {r.status_code}")
    print("keys:", sorted(data.keys()))
    print("address:", json.dumps(data.get("address"), ensure_ascii=False))
    print("display_name:", data.get("display_name"), "| error:", data.get("error"))


def search(client: httpx.Client, q: str) -> None:
    """Search for a place restricted to India and print the top results."""
    r = client.get(f"{BASE}/search", params={
        "q": q, "countrycodes": "in", "format": "jsonv2", "limit": 5, "addressdetails": 1, "accept-language": "en"})
    print(f"\n== search {q!r} HTTP {r.status_code}")
    for item in r.json():
        a = item.get("address", {})
        print(f"  {item['lat']},{item['lon']} name={item.get('name')!r} type={item.get('type')} "
              f"district={a.get('state_district') or a.get('county')} state={a.get('state')}")


def main() -> None:
    """Run the reverse and search probes, waiting between calls."""
    with httpx.Client(headers={"User-Agent": UA}, timeout=10) as client:
        for lat, lon in [(20.0, 73.79), (18.5, 70.0), (25.0, 68.0)]:
            reverse(client, lat, lon)
            time.sleep(1.1)
        search(client, "Niphad")


if __name__ == "__main__":
    main()
