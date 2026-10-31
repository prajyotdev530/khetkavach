"""Live smoke tests: one per data source, calling the real APIs (BUILD_SPEC §12).

Run before deploying with `pytest -m live`. They check shapes and physical ranges only, because the values
change with the real weather and imagery. Test point: a location near Nashik, Maharashtra (20.0, 73.79).
"""

import pytest

from app import cache
from app.sources import baseline, geocode, satellite_optical, satellite_radar, weather
from app.sources.common import analysis_box, today_ist

pytestmark = pytest.mark.live
LAT, LON = 20.0, 73.79


@pytest.fixture(autouse=True)
def fresh_cache():
    """Start every test with an empty in-process cache so it really calls the provider."""
    cache.clear_memory()


async def test_forecast_live():
    """Open-Meteo returns 16 forecast days with every derived field in a physical range."""
    f = await weather.get_forecast(LAT, LON, today_ist())
    assert f.forecast_days >= 7 and len(f.dates) == 16
    assert f.rain_next16_mm >= 0 and f.et0_next16_mm > 0
    assert 0 <= f.longest_dry_run_days <= 16
    assert f.soil_moisture_root is None or 0 < f.soil_moisture_root < 0.7
    assert f.source.fetched_at.utcoffset().total_seconds() == 19800


@pytest.mark.parametrize("provider", ["era5", "nasa_power"])
async def test_baseline_live(provider):
    """Both historical providers give a 20-year normal for these calendar windows."""
    b = await baseline.get_baseline(LAT, LON, today_ist(), provider)
    assert b.years_used >= 18 and b.provider == provider
    assert len(b.tmax_next16_normal_c) == 16 and 10 < b.tmax_next16_normal_mean < 45


async def test_geocode_live():
    """A Nashik point resolves to Maharashtra; a sea point and a Pakistan point are rejected; search works."""
    place = await geocode.reverse(LAT, LON)
    assert place.state == "Maharashtra" and place.country_code == "in"
    with pytest.raises(geocode.RejectedLocation):
        await geocode.reverse(18.5, 70.0)
    with pytest.raises(geocode.RejectedLocation):
        await geocode.reverse(25.0, 68.0)
    hits = await geocode.search("Niphad")
    assert hits and all(h.state for h in hits)


async def test_optical_live():
    """Sentinel-2 returns NDVI/NDMI in range with a scene date, plus PNG overlays under 60 KB."""
    r = await satellite_optical.get_optical_index(LAT, LON, analysis_box(LAT, LON), today_ist())
    assert -1 <= r.ndvi.median <= 1 and -1 <= r.ndmi.median <= 1
    assert r.clear_fraction >= 0.6
    assert {o.layer for o in r.overlays} >= {"ndvi", "truecolor"}
    assert all(len(o.png_base64) * 3 / 4 <= 60_000 for o in r.overlays)


async def test_radar_live():
    """Sentinel-1 RTC returns VH/VV backscatter in dB and a change vs last year."""
    r = await satellite_radar.get_radar_index(LAT, LON, analysis_box(LAT, LON), today_ist())
    assert r.calibrated and -35 < r.vh_db < 5
    assert r.delta_vh_db is None or -20 < r.delta_vh_db < 20
