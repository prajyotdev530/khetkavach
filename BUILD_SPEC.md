# KhetKavach build spec

This tab is the implementation spec for Claude Code. Build exactly what's described here, in the order given. Where a value is marked **VERIFY**, check it against the provider's live docs before coding.

## 1. How to use this spec

Build in the order below. Each step must work on real data before the next one starts. Feature IDs (F1–F16) match the PRD tab.

**Build order:**

1. **Data spikes:** a small script per source (Planetary Computer, Open-Meteo forecast + archive, NASA POWER, Nominatim, Sarvam, Gemini) that prints real output for one test point, for example a farm near Nashik (20.0, 73.79). Commit these as `backend/scripts/spike_*.py`.
2. **Fetchers + risk engine** (F2–F6) as plain Python modules with unit tests.
3. **FastAPI + streaming endpoint + LangGraph agent** (F7, F8, F10).
4. **Frontend:** map, trace panel, risk card, overlay (F1, F12, F7 UI).
5. **Sarvam translation and voice** (F9).
6. **Deploy** both apps; test from the public URLs.
7. **P1 items** (F11, F13, F14, F15) only after everything above passes the acceptance checklist (section 12).

**Hard rules (breaking these means disqualification or lost points):**

- **No dummy data.** No hardcoded JSON fixtures, no random number generators for values, no placeholder numbers in the UI. Every number shown comes from a live API call or a cache entry of a real response with its `fetched_at` time.
- **No secrets in the repo.** Use `.env` locally and platform secrets in deployment; commit `.env.example` only.
- **The LLM never computes numbers.** All numbers come from tool outputs. The LLM only plans, picks tools and writes text.
- **Readable code.** Add a short docstring to every module and function explaining what it does and why, in plain English. Team members must be able to explain any file (rule 6).
- **Never crash.** Every external call has a timeout, a retry policy and a defined fallback (section 10).

**Definition of done for a feature:** it works on the deployed URL; it handles its failure cases from section 10; its acceptance items in section 12 pass; it shows a source and timestamp for every number.

## 2. Repo structure, stack & environment

Use one repo with two apps. The backend runs in Docker on Hugging Face Spaces; the frontend runs on Vercel.

```text
khetkavach/
  README.md                  # setup, architecture diagram, data provenance
  .env.example
  backend/
    Dockerfile               # python:3.11-slim, listens on port 7860 (HF Spaces)
    pyproject.toml
    app/
      main.py                # FastAPI app, CORS, routes
      config.py              # settings from env + risk thresholds (risk.yaml)
      risk.yaml              # every threshold, with a comment on its origin
      models.py              # Pydantic schemas (section 5)
      sources/               # one module per external source
        satellite_optical.py # Sentinel-2 via Planetary Computer
        satellite_radar.py   # Sentinel-1 fallback
        weather.py           # Open-Meteo forecast
        baseline.py          # Open-Meteo archive + NASA POWER
        geocode.py           # Nominatim
        sarvam.py            # translate, TTS, STT
      engine/
        crops.py             # crop stage tables
        risk.py              # drought / excess rain / heat scores
        overlay.py           # NDVI to coloured PNG
      agent/
        graph.py             # LangGraph state graph
        prompts.py
        validator.py         # citation validator
      cache.py               # Supabase-backed cache
      events.py              # stream event helpers
    scripts/spike_*.py
    tests/
  frontend/
    package.json             # React 18 + Vite + TypeScript
    src/
      App.tsx
      pages/ (Home.tsx, Batch.tsx, Share.tsx)
      components/ (MapView, TracePanel, RiskCard, ActionPlan,
                   VoicePlayer, LanguagePicker, Legend,
                   BeforeNowSlider, SearchBox, SourceBadge)
      lib/ (api.ts, sse.ts, colors.ts)
```

**Stack:** Python 3.11, FastAPI, sse-starlette, LangGraph, google-genai, httpx (async), pystac-client, planetary-computer, odc-stac, rioxarray, numpy, Pillow, supabase-py, pydantic v2. Frontend: React 18, Vite, TypeScript, Tailwind, shadcn/ui, react-leaflet, Leaflet.

| Variable | Where | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | backend | Agent LLM (free tier) |
| `GEMINI_MODEL` | backend | Model name; **VERIFY** the current free-tier model with tool calling |
| `SARVAM_API_KEY` | backend | Translation, TTS, STT |
| `SUPABASE_URL`, `SUPABASE_KEY` | backend | Cache + share links (service-role key, backend only) |
| `NOMINATIM_USER_AGENT` | backend | Required by Nominatim policy, e.g. `KhetKavach/1.0 (team email)` |
| `ALLOWED_ORIGINS` | backend | The Vercel URL, for CORS |
| `DEMO_CONTROLS` | backend | `true` enables the failure-simulation parameter (section 11) |
| `VITE_API_URL` | frontend | Backend base URL |

## 3. Screens & UI

There are three routes. The home screen is a map on the left (60% width) and a results panel on the right (40%). On phones they stack.

| Route | Purpose |
| --- | --- |
| `/` | Analyse one farm (the main demo screen) |
| `/batch` | FPO / lender view: many farms as risk pins + a sorted table (F13) |
| `/a/:id` | Read-only share page for a saved analysis (F15) |

**Home screen, top to bottom:**

1. **Header:** "KhetKavach" wordmark, the tagline "Farm-level climate risk, in your language", the language picker (section 9) and a link to Batch.
2. **Input bar** (above the results panel):
   - **Crop:** Wheat, Mustard, Gram (chickpea), or "Not sure". "Not sure" uses generic thresholds and lowers confidence by one step.
   - **Sowing date:** a date picker, optional. If it's empty, the crop stage is "unknown" and stage-specific advice is skipped.
   - **Quick farms:** 3 chips with real coordinates the team picks for the demo (section 11). They only move the map and start a normal live analysis.
3. **Map** (section 4): search box top-left, layer toggle top-right, legend bottom-left.
4. **Results panel** with tabs **Trace | Risk | Plan | Evidence**. It switches to Risk automatically when the run finishes.

**Components:**

- **TracePanel (F7):** one row per agent step: an icon (spinner = running, check = done, amber triangle = fallback, red x = failed), a plain-English label ("Fetching satellite image from 27 Oct"), duration in ms, and a source chip. Rows can expand to show the tool's summary output. It auto-scrolls and stays visible during the run.
- **RiskCard (F6):** three horizontal score bars (Drought, Excess rain, Heat). Each shows the 0–100 score, a level word (Low / Moderate / High) in its colour, and its top 2 drivers as sentences with source chips. Above them: a confidence badge (High / Medium / Low) and "Data as of" with the newest `fetched_at`.
- **ActionPlan (F8):** 3–5 cards, each with a date ("by 6 Nov"), the action, a one-line reason, and citation chips. Hovering a chip shows the source name, value and fetch time.
- **Evidence tab:** a 16-day chart with daily rain bars and a max-temperature line, both with the 20-year normal as a dashed line (Recharts). Below it, NDVI and NDMI now vs last year, plus the satellite scene date and cloud %.
- **VoicePlayer (F9):** play/pause, progress bar, language name, and a "Voice by Sarvam" note. It's disabled with a tooltip while audio is generating.
- **SourceBadge:** a small pill ("Sentinel-2 · 27 Oct", "Open-Meteo · 3 min ago") linking to the provider's page.
- **Share button (F15):** copies `/a/:id` to the clipboard.

**Screen states:**

| State | What shows |
| --- | --- |
| Idle | Map of India; panel says "Click any farm in India or search a village" |
| Running | Trace streams live; Risk and Plan tabs show skeleton loaders |
| Done | Full results; the farm box gets its risk colour (section 4) |
| Partial | Results + an amber banner naming the missing sources, e.g. "Forecast unavailable, using recent observations" |
| Rejected | Calm message, e.g. "That point is outside India or over water. Pick a farm on land in India." No run starts |
| Error | A red banner with the reason and a Retry button; the map stays usable |

**Mobile (<768 px):** the map takes the top 45% of the screen, and the results tabs sit below it. Every control is at least 44 px tall.

**Accessibility:** colour is never the only signal; levels are always written as words too. All controls work by keyboard. Contrast is at least 4.5:1.

## 4. Map visuals (F1, F12, F13)

The farm "turning red" shows the **forecast risk level**, drawn as the analysis box's outline and fill. The satellite colour layers show **evidence** (crop health now and its change vs last year) and sit underneath.

This split matters. In November, newly sown rabi fields are mostly bare soil and naturally show low greenness. A raw greenness layer would paint them red even when nothing is wrong, so "red" must never mean low greenness alone.

**Base map and navigation:**

- Default view: centre \[22.5, 79.0\], zoom 5 (all of India). When a farm is picked, fly to it at zoom 16 over 1.2 s.
- Base layers: Esri World Imagery (default, satellite look) `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` and OpenStreetMap `https://tile.openstreetmap.org/{z}/{x}/{y}.png`, with attribution shown for both.
- Click anywhere to drop a pin and start a run. Search results do the same.
- **Analysis box:** a 500 m square centred on the pin. Half-side offsets: 250 / 111,320 degrees of latitude and 250 / (111,320 × cos(lat)) degrees of longitude. The backend returns the exact bounds it used; the frontend draws those.

**Layer 1: risk outline (the "turning red" moment, P0):**

| Overall level | Outline + label colour | Fill |
| --- | --- | --- |
| Low | #2E7D32 (green) | same colour, 15% opacity |
| Moderate | #F9A825 (amber) | same colour, 15% opacity |
| High | #C62828 (red) | same colour, 20% opacity |

- Overall level = the highest of the three risk levels.
- While the agent runs, the box outline is grey (#9E9E9E), dashed, and pulses (opacity 0.4 to 1, every 1.2 s).
- When the risk result arrives, the outline turns solid 3 px and fades from grey to the level colour over 800 ms. On **High**, it pulses 3 times, then holds steady.
- A label pinned above the box reads, for example, "High drought risk · 72". It names the hazard with the top score and its score.

**Layer 2: crop-health overlays (evidence, P0):** the backend returns PNGs with transparent masked pixels, plus their bounds; show them with `L.imageOverlay` at 70% opacity.

| Layer | Values | Colours (low to high) | Default |
| --- | --- | --- | --- |
| Change vs last year | ΔNDVI = NDVI now − NDVI same window last year | ≤ −0.20 #B2182B · −0.20 to −0.05 #EF8A62 · ±0.05 #F0F0F0 · 0.05 to 0.20 #91CF60 · ≥ 0.20 #1A9850 | On |
| Green cover now | NDVI | < 0.15 #A50026 · 0.15–0.30 #F46D43 · 0.30–0.45 #FEE08B · 0.45–0.60 #A6D96A · ≥ 0.60 #1A9850 | Off |
| True colour | Sentinel-2 bands B04, B03, B02, reflectance scaled 0–3000 with gamma 1.2 | natural colour | Off |
| Radar (only when used) | Sentinel-1 VH backscatter change vs last year, in dB | same ramp as "Change vs last year" | Auto when optical is cloudy |

Masked pixels (cloud, cloud shadow, cirrus, water, no data) are fully transparent. The legend notes how much of the box was masked, e.g. "18% hidden by cloud".

**Before/now slider (F12, P0):** a range input (0–100) under the map crossfades two overlays: the same layer for last year and now. The labels show the actual scene dates, e.g. "28 Oct 2025" and "27 Oct 2026". A toggle switches the slider between True colour and Green cover.

**Legend (bottom-left, P0):** shows the colour ramp of the active evidence layer with words ("less green than last year", "no change", "greener"), the three risk colours with their words, the scene date and the masked %.

**Batch pins (F13, P1):** circle markers, radius 9 px, filled with the overall level colour, white 2 px border. Clicking one opens a popup with the three scores, the village name and an "Open full analysis" link. The map fits its bounds to all pins.

**Layer control (top-right):** Satellite / Street base map; checkboxes for Risk outline, Change vs last year, Green cover now, True colour.

## 5. Backend API & event stream

One streaming endpoint drives the main demo. Everything else is plain JSON. All responses carry `fetched_at` timestamps in ISO 8601 with the IST offset.

| Method & path | Input | Output |
| --- | --- | --- |
| `GET /health` | none | `{status, version, sources: {name: "ok" or "degraded"}}`; used by the keep-alive ping |
| `GET /api/analyze` | query: `lat`, `lon`, `crop` (wheat, mustard, gram, unknown), `sowing_date?` (YYYY-MM-DD), `lang` (default `en-IN`), `fail?` (demo only, section 11) | Server-Sent Events stream (below) |
| `GET /api/analysis/{id}` | none | The saved full result, for share pages |
| `GET /api/search` | `q` (≥ 3 characters) | Up to 5 places in India: `{name, district, state, lat, lon}`. Proxies Nominatim, cached, rate-limited to 1 request per second |
| `POST /api/translate` | `{analysis_id, lang}` | The plan and summary in that language (cached) |
| `POST /api/tts` | `{analysis_id, lang}` | `{audio_base64, mime: "audio/wav", chars}` (cached) |
| `POST /api/ask` (P1) | `{analysis_id, question, lang}`, or multipart audio | `{answer, citations}`, grounded only in that analysis's tool outputs |
| `POST /api/batch` (P1) | `{crop, points: [{lat, lon, label?}]}`, max 20 | SSE: one `batch_item` event per point (3 run in parallel), then `batch_done` |

The frontend uses `EventSource` for `/api/analyze`. The backend sends a keep-alive comment every 15 s.

**Stream events, in typical order:**

| Event | Data fields | UI reaction |
| --- | --- | --- |
| `run_started` | `run_id, lat, lon, place, crop, stage, bounds` | Draw the grey pulsing box; show the place name |
| `plan` | `steps: [{id, tool, reason}]` | Trace shows the plan |
| `tool_started` | `call_id, tool, label, args` | Spinner row |
| `tool_succeeded` | `call_id, tool, duration_ms, summary, source: {name, url, fetched_at, scene_date?}` | Tick + source chip |
| `tool_failed` | `call_id, tool, error_code, message, will_retry` | Red or amber row |
| `fallback` | `from_tool, to_tool, reason` | Amber row, e.g. "Cloud 85% → switching to radar" |
| `overlay` | `layer` (delta\_ndvi, ndvi, truecolor, radar), `period` (now, last\_year), `png_base64, bounds, scene_date, masked_pct` | Add the map layer |
| `risk` | `scores: [RiskScore], overall_level, confidence` | Box turns its colour; RiskCard fills |
| `action_plan` | `summary, actions: [Action], lang: "en-IN"` | Plan tab fills |
| `validation` | `numbers_checked, numbers_rejected, regenerated` | Trace row "12 numbers checked, 0 rejected" |
| `translation` | `lang, summary, actions` | Plan switches language |
| `partial` | `missing: [source names]` | Amber banner |
| `run_completed` | `run_id, analysis_id, duration_ms` | Enable Share and Voice |
| `error` | `code, message, retryable` | Red banner + Retry |

**Core schemas (Pydantic, mirrored as TypeScript types in `lib/api.ts`):**

```text
Citation   { call_id, source, field, value, unit, fetched_at }
Driver     { text, citations: [Citation] }
RiskScore  { hazard: drought|excess_rain|heat, score: 0-100,
             level: low|moderate|high, drivers: [Driver] }
Action     { by_date: YYYY-MM-DD, action, reason, citations: [Citation] }
Analysis   { id, created_at, lat, lon, place, crop, stage, bounds,
             evidence: {optical?, radar?, forecast?, baseline?},
             scores: [RiskScore], overall_level, confidence,
             summary, actions: [Action], missing: [str], trace: [event] }
```

## 6. Data pipeline

Each source module exposes one async function returning a typed result with `source`, `url` and `fetched_at`. Read only the 500 m box from the satellite data, never whole scenes.

**Shared rules:** httpx async client; 8 s timeout per HTTP call and 25 s per satellite load; 2 retries with 0.5 s and 1.5 s backoff on timeout, 429 or 5xx; on final failure raise `SourceUnavailable(source, reason)`, which the agent turns into a fallback.

### 6.1 Optical satellite: `satellite_optical.py` (F2)

- STAC API `https://planetarycomputer.microsoft.com/api/stac/v1`, collection `sentinel-2-l2a`, signed with `planetary_computer.sign_inplace`.
- Search: bbox = analysis box; dates = last 30 days; scene cloud `eo:cloud_cover < 80`; newest first; up to 6 scenes.
- Load bands B02, B03, B04, B08, B11 and SCL with `odc.stac.load` at 10 m (B11 resampled bilinear, SCL nearest).
- **Cloud mask from SCL:** keep classes 4 (vegetation), 5 (not vegetated) and 7 (unclassified). Mask 0, 1, 2, 3 (shadow), 6 (water), 8, 9 (cloud), 10 (cirrus) and 11 (snow).
- `clear_fraction` = unmasked pixels / all pixels. Take the newest scene with `clear_fraction ≥ 0.6`. None in 30 days: widen to 45 days once. Still none: raise `TooCloudy`, which triggers the radar fallback (F3).
- **Reflectance:** for scenes with `s2:processing_baseline ≥ 04.00`, subtract the 1000 offset, then divide by 10,000 and clip at 0. **VERIFY** against the Planetary Computer Sentinel-2 docs.
- Indices: NDVI = (B08 − B04) / (B08 + B04); NDMI = (B08 − B11) / (B08 + B11). Report the median over clear pixels, plus the 10th and 90th percentiles.
- **Last year:** the same steps for a ±15-day window around the scene date minus 365 days. Report `delta_ndvi` and `delta_ndmi` = now − last year.
- Hand the arrays to `engine/overlay.py` to make the PNGs for section 4. Return `{scene_date, scene_cloud_pct, clear_fraction, ndvi, ndmi, ndvi_last_year, ndmi_last_year, delta_ndvi, delta_ndmi, last_year_scene_date}`.

### 6.2 Radar fallback: `satellite_radar.py` (F3)

- Collection `sentinel-1-rtc`; if it can't be accessed, use `sentinel-1-grd`. **VERIFY** access in the Phase 1 spike.
- Bands VV and VH; convert to dB (10 × log10). Window: last 24 days and the same window last year.
- Return the median VH dB now and last year, `delta_vh_db`, the VH/VV ratio and the scene dates. Lower VH than last year suggests less crop biomass. Label confidence one step lower than optical.

### 6.3 Forecast: `weather.py` (F4)

- `GET https://api.open-meteo.com/v1/forecast` with latitude, longitude, `timezone=Asia/Kolkata`, `forecast_days=16`, `past_days=30`.
- Daily fields: `precipitation_sum`, `precipitation_probability_max`, `temperature_2m_max`, `temperature_2m_min`, `et0_fao_evapotranspiration`. Hourly fields: `soil_moisture_3_to_9cm`, `soil_moisture_9_to_27cm`. **VERIFY** the variable names in the Open-Meteo docs.
- Derived values, all computed in code:
  - `rain_next16_mm` (sum)
  - `max_3day_rain_mm` (highest rolling 3-day sum)
  - `longest_dry_run_days` (longest run of days under 2.5 mm, the threshold IMD uses for a rainy day)
  - `et0_next16_mm`
  - `water_deficit_mm` = et0\_next16 − rain\_next16
  - `soil_moisture_root` (mean of the two soil layers over the next 72 h)
  - `rain_past30_obs_mm` (from the `past_days` data)
  - `tmax_series` and `rain_series` for the Evidence chart

### 6.4 Historical normal: `baseline.py` (F5)

- Primary: `GET https://archive-api.open-meteo.com/v1/archive` for 2006-01-01 to 2025-12-31 (20 years), with daily `precipitation_sum` and `temperature_2m_max`, in one call.
- Fallback: NASA POWER `GET https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,T2M_MAX&community=AG&latitude=..&longitude=..&start=20060101&end=20251231&format=JSON`.
- For each year, take the same calendar windows (the past 30 days and the next 16 days), then average across years. Return `rain_past30_normal_mm`, `rain_next16_normal_mm`, `tmax_next16_normal_c` (per day, for the chart), `rain_past30_anomaly_pct` = (obs − normal) / normal × 100 (set to null when normal < 5 mm), and `years_used`.

### 6.5 Places: `geocode.py` (F1)

- Reverse: `GET https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=..&lon=..&zoom=14&addressdetails=1&accept-language=en`. If `country_code` isn't `in`, or there's no address, the point is **rejected** (outside India or over water).
- Search: `/search?q=..&countrycodes=in&format=jsonv2&limit=5&addressdetails=1`.
- Send the `User-Agent` header from env; allow at most 1 request per second globally (an asyncio lock); cache results for 30 days.

## 7. Risk engine (F6)

Scores are a transparent weighted sum of evidence, computed in `engine/risk.py`. Every threshold and weight lives in `risk.yaml`, with a comment that says it's a default to be reviewed by an agronomist, so judges can see nothing is hidden.

**Crop stages** (days after sowing). Stages marked \* are sensitive.

| Crop | Stages (days after sowing) | Heat threshold, max temperature (sensitive stages / other) |
| --- | --- | --- |
| Wheat | 0–20 emergence · 21–25 crown-root initiation\* (key irrigation) · 26–45 tillering · 46–70 jointing/booting · 71–95 heading/flowering\* · 96–120 grain filling\* · 121+ maturity/harvest\* | 32 °C / 34 °C |
| Mustard | 0–15 emergence · 16–35 vegetative · 36–60 flowering\* · 61–100 pod filling\* · 101+ maturity/harvest\* | 30 °C / 33 °C |
| Gram | 0–20 emergence · 21–45 branching · 46–75 flowering\* · 76–105 pod filling\* · 106+ maturity/harvest\* | 32 °C / 35 °C |
| Not sure | stage unknown | 35 °C |

Helper: `lin(x, a, b)` = clamp((x − a) / (b − a) × 100, 0, 100). It maps a value to 0–100 between a "no concern" point a and a "full concern" point b.

**Drought score:**

| Component | Formula | Weight |
| --- | --- | --- |
| D1 water deficit | lin(water\_deficit\_mm, 10, 60) | 0.30 |
| D2 dry spell | lin(longest\_dry\_run\_days, 5, 14); **set to 0 when rain\_next16\_normal\_mm < 10** (dry weeks are normal that season) and give its weight to D1 | 0.15 |
| D3 soil moisture | lin(0.30 − soil\_moisture\_root, 0, 0.18), in m³/m³ | 0.20 |
| D4 crop moisture vs last year | lin(−delta\_ndmi, 0.02, 0.15); radar instead: lin(−delta\_vh\_db, 0.5, 3.0) | 0.20 |
| D5 past-month rain | lin(−rain\_past30\_anomaly\_pct, 20, 80); skip when the anomaly is null | 0.15 |

At water-sensitive stages (wheat crown-root initiation and flowering, mustard flowering), multiply by 1.15 and cap at 100.

**Excess / unseasonal rain score:**

| Component | Formula | Weight |
| --- | --- | --- |
| E1 heavy burst | lin(max\_3day\_rain\_mm, 20, 80) | 0.45 |
| E2 unseasonal total | lin(rain\_next16\_mm − rain\_next16\_normal\_mm, 10, 60) | 0.25 |
| E3 rain likelihood | lin(max precipitation\_probability over the next 7 days, 40, 90) | 0.15 |
| E4 waterlogging | lin(soil\_moisture\_root, 0.35, 0.45) | 0.15 |

At flowering and maturity/harvest stages, multiply by 1.3 and cap at 100.

**Heat score:**

| Component | Formula | Weight |
| --- | --- | --- |
| H1 hot days | lin(days in the next 16 with max temp ≥ stage threshold, 0, 6) | 0.50 |
| H2 peak excess | lin(highest max temp − threshold, 0, 5) | 0.30 |
| H3 warmer than normal | lin(mean max temp next 16 − normal for those days, 1, 5) | 0.20 |

**Missing evidence:** drop the missing components and rescale the remaining weights to sum to 1. A hazard with under 50% of its weight available is shown as "Not enough data", with no score.

**Levels:** 0–33 Low, 34–66 Moderate, 67–100 High. Overall level = the highest of the three.

**Drivers:** for each hazard, take the 2 components with the largest weighted contribution and fill a sentence template with their real values, e.g. "Evaporation will exceed rain by 46 mm over the next 16 days". Each sentence carries the citation of the tool call that produced the value.

**Confidence:** start at High and step down once for each of: radar used instead of optical, baseline missing, crop "Not sure", forecast missing. The floor is Low.

**Unit tests** must cover each component at its a and b points, weight rescaling with missing evidence, the D2 rule, the stage multipliers and the level boundaries (33/34, 66/67).

## 8. Agent (F7, F8)

The agent is a LangGraph state graph. The LLM handles three jobs: planning, choosing a recovery, and writing. Everything else is deterministic code, so the demo can't fail because the model had a bad moment. Budget: at most 4 LLM calls per run, to stay within free-tier limits.

**State:** `request` (lat, lon, crop, sowing\_date, lang), `place`, `stage`, `plan`, `calls` (call\_id → tool, args, status, result, source, duration), `evidence`, `scores`, `draft`, `validation`, `translation`, `missing`, `round`.

**Nodes, in order:**

1. **`check_location`** (code): reverse geocode; if the point is outside India or over water, emit `error` with code `REJECTED_LOCATION` and end. Compute the crop stage.
2. **`plan`** (LLM with function calling): given the tool catalogue and the request, return the tool calls to make and a one-line reason for each. Code then **guarantees** the required set (optical, forecast, baseline) is present, adding any the model left out. Emit `plan`.
3. **`gather`** (code): run the planned calls concurrently with `asyncio.gather`; emit `tool_started`, `tool_succeeded` and `tool_failed` events.
4. **`check`** (code): mark each result usable or not: optical clear fraction ≥ 0.6, no null-only series, forecast covers ≥ 7 days.
5. **`recover`** (LLM, with a code fallback): for each failed or unusable result, the LLM picks from that tool's allowed fallbacks (table below) and gives a reason; emit `fallback`. If the LLM errors or picks something not allowed, use the first allowed fallback. Go back to `gather`, at most 2 rounds; then mark the rest as missing and emit `partial`.
6. **`score`** (code): the risk engine (section 7); emit `risk` and the `overlay` events.
7. **`write`** (LLM, JSON-schema output): produce the summary and 3–5 actions with citations.
8. **`validate`** (code): the citation validator below; emit `validation`. On failure, rewrite once with the problems listed; if it still fails, drop the failing lines. If fewer than 2 actions are left, use template actions built from the drivers.
9. **`localise`** (code): Sarvam translation when `lang` isn't English (section 9); emit `translation`.
10. **`save`** (code): store the full analysis in Supabase; emit `run_completed`.

| Tool | Allowed fallbacks |
| --- | --- |
| `get_optical_index` | same tool with a 45-day window, then `get_radar_index` |
| `get_radar_index` | GRD collection, then mark crop evidence missing |
| `get_forecast` | retry once, then mark forecast missing (heat and excess-rain scores become "Not enough data") |
| `get_baseline` | NASA POWER, then mark baseline missing |
| `geocode` | coordinates only, labelled "Unnamed place" |

Use the `google-genai` SDK. Function calling and JSON-schema output go in **separate** calls (plan and recover use tools; write uses `response_schema`). LLM timeout: 15 s per call. A failed `plan` falls back to the required set.

**Write prompt** (system part, stored in `prompts.py`):

```text
You are KhetKavach, an agronomy assistant for Indian farmers.
You receive EVIDENCE: tool outputs, each with a call_id and fields.
Write a summary (max 60 words) and 3 to 5 actions for the next
16 days for this crop and stage.
Rules:
- Use ONLY numbers that appear in EVIDENCE. Never estimate or round
  beyond one decimal. Every number must be cited as call_id.field.
- Each action has by_date (YYYY-MM-DD within the forecast window),
  a concrete action a smallholder can take, and a one-line reason.
- Prioritise the highest-scoring hazard.
- No pesticide or fertiliser brand names or doses; say "consult your
  local KVK or agriculture officer" for chemical decisions.
- If confidence is Low, say what data was missing.
- Plain, simple English (it will be translated).
```

Output schema: `{summary: string, actions: [{by_date, action, reason, citations: ["call_id.field"]}] (3-5 items)}`.

**Citation validator (`validator.py`):**

- Pull every number out of the summary and each action with a regex (integers, decimals, negatives, numbers followed by a unit or %).
- Each number must match a value in the evidence fields it cites: absolute difference ≤ 0.5, or relative difference ≤ 2%. Tool arguments such as "16 days" count as valid values.
- Every citation must point to a real call\_id and field. Every `by_date` must fall within today to today + 16 days.
- Output: `{numbers_checked, numbers_rejected, failing_lines}`. Unit tests should include a deliberately invented number, which must be caught.

## 9. Language & voice: Sarvam (F9, F11)

The agent always writes in English first, so the validator checks one language. Sarvam then translates the checked text and reads it aloud. Numbers must survive translation unchanged.

**Language picker:** the 9 languages that have both text and voice in [Bulbul v4](https://docs.sarvam.ai/api/getting-started/models.md): English (en-IN), Hindi (hi-IN), Marathi (mr-IN), Bengali (bn-IN), Gujarati (gu-IN), Kannada (kn-IN), Punjabi (pa-IN), Tamil (ta-IN), Telugu (te-IN). Other Sarvam-Translate languages can be listed under "Text only" if time allows. The picker shows each language in its own script, e.g. "हिन्दी".

| Call | Endpoint & model | Spec |
| --- | --- | --- |
| Translate | `POST https://api.sarvam.ai/translate`, model Sarvam-Translate | Translate the summary and each action/reason as separate items so the structure survives. Ask for international (0–9) numerals if the API supports it. **VERIFY** the model id and parameters |
| Text-to-speech | `POST https://api.sarvam.ai/text-to-speech`, Bulbul v4 | Speak the summary + the top 3 actions, at most 1,500 characters. Split into chunks if the API has a per-request limit and join the WAVs. One default voice per language, pace about 0.95. **VERIFY** the model id, voice names and character limit |
| Speech-to-text (P1) | `POST https://api.sarvam.ai/speech-to-text`, Saaras v4 | Record up to 30 s in the browser (MediaRecorder), transcribe with language auto-detect, then send the text to `/api/ask` |

All calls send the `api-subscription-key` header from `SARVAM_API_KEY`.

**Number check after translation:** pull the numbers from the English and the translated text. If they differ (for example, a number was dropped or converted to native digits), show the English for that line with a small "(English)" tag rather than risk a wrong number.

**Cost and caching:** new accounts get ₹100 of free credit; Bulbul v4 is about ₹1 per 1,000 characters. Cache translations and audio in Supabase, keyed by sha256(model + language + voice + text), so demo repeats cost nothing. Show the cached audio instantly.

**Failures:** if translation fails, show English with the note "Translation unavailable right now". If text-to-speech fails, the play button is disabled with "Voice unavailable", and the text still shows. Neither blocks the analysis.

## 10. Edge cases & error handling (F10)

The demo is worth 30 points, and "edge case resilience" is half of that pillar, so every row below needs a test and a visible, calm UI response.

| Situation | Detection | System response | User sees |
| --- | --- | --- | --- |
| Click in the ocean or outside India | Reverse geocode: no address, or country isn't `in` | Stop before any data calls | "That point is outside India or over water. Pick a farm on land in India." |
| Click on a city, river or forest | Optical SCL: water > 50%, or NDVI median < 0.1 with no crop history | Still analyse, but add a note | Amber note: "This looks like a built-up area or water, not a farm. Results may not apply." |
| Optical image cloudy | `clear_fraction < 0.6` | Widen to 45 days, then switch to radar | Trace: "Cloud 85% → switching to radar"; confidence drops one step |
| No radar either | `SourceUnavailable` | Mark crop evidence missing; continue with weather | Partial banner; drought score rescaled |
| Open-Meteo forecast down or times out | Timeout or 5xx after 2 retries | Mark forecast missing; heat and excess rain show "Not enough data" | Partial banner; past-30-days evidence still shown |
| Archive down | Same | NASA POWER fallback | Trace shows the switch; source chip reads "NASA POWER" |
| Both baselines down | Same | Skip the anomaly components; confidence drops | Partial banner |
| Gemini rate-limited (429) or down | Exception or timeout | plan → use the required tool set; recover → first allowed fallback; write → template actions from the drivers | Plan still appears, marked "Generated from rules" |
| LLM invents a number | Validator | Rewrite once, then drop the line | Trace: "1 number rejected, line removed" |
| Sarvam down or out of credit (402/429) | HTTP status | Show English; disable voice | "Translation/voice unavailable right now" |
| Nominatim rate limit | 429 | Wait 1 s and retry; then coordinates only | Place shows "20.00°N, 73.79°E" |
| Invalid input (lat/lon out of range, future sowing date, unknown crop) | Pydantic validation | 422 with a clear message | An inline form error, no run |
| User clicks again mid-run | Frontend | Close the old EventSource and start a new run | The old trace clears |
| Network drops mid-stream | EventSource `onerror` | Reconnect once; then show Retry | "Connection lost — Retry" |
| Whole run takes over 45 s | Server timer | Return a partial result from what's ready | Partial banner |
| Backend asleep or redeploying | `/health` fails | Frontend retries `/health` for 20 s with a spinner | "Waking up the server…" |

The backend never returns a raw stack trace. Every error has a `code`, a human `message` and `retryable`.

## 11. Caching, performance & demo controls

Caching keeps the demo fast and the free tiers alive. It stores only real responses, each with its fetch time, and the UI always says when something came from the cache.

**Supabase tables:**

- `cache(key text primary key, value jsonb, source text, fetched_at timestamptz, expires_at timestamptz)`
- `analyses(id uuid primary key, created_at, lat, lon, crop, payload jsonb)` for share links
- `media(key text primary key, lang, kind, data text, created_at)` for translations and audio

| Data | Cache key | Lifetime |
| --- | --- | --- |
| Place names | lat/lon rounded to 0.001° | 30 days |
| Optical / radar result now | lat/lon rounded to 0.002° + scene id | 24 h |
| Optical / radar last year | same + last year's scene id | 30 days |
| Forecast | lat/lon rounded to 0.01° | 1 h |
| Historical normal | lat/lon rounded to 0.05° | 30 days |
| Translation, audio | sha256 of the inputs | permanent |

When a value comes from the cache, its source chip reads "Open-Meteo · fetched 12 min ago (cached)". It's never presented as just fetched.

**Performance budgets:**

| Metric | Target |
| --- | --- |
| First trace event after a click | ≤ 1 s |
| Full run, nothing cached | ≤ 30 s (hard cap 45 s, then a partial result) |
| Full run, cached | ≤ 3 s |
| Overlay PNG size | ≤ 60 KB each |
| Frontend bundle | ≤ 500 KB gzipped |

Run the satellite (now and last year), forecast and baseline calls in parallel. Import the heavy geospatial libraries when the server starts, not on the first request. A free uptime monitor (e.g. UptimeRobot) pings `/health` every 10 minutes during the event.

**Demo controls** (only when `DEMO_CONTROLS=true`):

- The `fail` parameter (`satellite`, `forecast`, `baseline`, `llm` or `sarvam`) makes that tool raise `SourceUnavailable`, to show recovery live.
- The trace labels it honestly: "Simulated outage: forecast (demo control)".
- Frontend: a small "Resilience test" menu, opened with Shift+D, lists these options.

**Quick-farm chips:** at hour 30, the team picks 3 real locations by running live analyses: (1) a rabi farm with a Moderate or High risk, (2) a farm in a cloudy region that triggers the radar fallback (in November, the northeast monsoon makes coastal Tamil Nadu a likely candidate), and (3) a healthy-looking farm for contrast. Store only their names and coordinates; every click still runs live.

## 12. Testing & acceptance checklist

The build is ready when every box below is ticked **on the deployed URLs**, not just locally.

**Automated tests (pytest, run in CI on every push):**

- Risk engine: every component at its a/b points, weight rescaling, the D2 rule, stage multipliers, level boundaries.
- Validator: a correct plan passes; a plan with an invented number fails; a bad citation fails; an out-of-window date fails.
- Overlay: a known small array gives the expected colours; masked pixels are transparent.
- Sources: one live smoke test per source, marked `@pytest.mark.live`, run before deploy rather than on every push.
- Event stream: a full run emits `run_started` first and `run_completed` or `error` last, with valid JSON in every event.

**Manual acceptance (P0):**

- [ ] Clicking a farm in Maharashtra streams the trace within 1 s and finishes in ≤ 30 s
- [ ] The box pulses grey while running, then turns its risk colour; High pulses 3 times
- [ ] The "Change vs last year" overlay appears with a legend, scene dates and masked %
- [ ] The before/now slider crossfades with the correct dates
- [ ] The RiskCard shows 3 scores, levels as words, drivers with source chips
- [ ] Every number in the Plan has a citation chip that shows its source on hover
- [ ] Validator trace row shows numbers checked and 0 rejected
- [ ] A cloudy farm triggers the radar fallback, shown in the trace and the legend
- [ ] Ocean and outside-India clicks are rejected politely
- [ ] Each demo control (satellite, forecast, baseline, llm, sarvam) produces a partial result, not a crash
- [ ] Hindi and Marathi plans render, and the voice plays
- [ ] A second identical run is ≤ 3 s and shows "(cached)" chips
- [ ] Works on a phone over mobile data, in incognito
- [ ] No API keys in the repo or in the browser's network tab (all external calls go through the backend)
- [ ] Searching the repo finds no fixture JSON and no random-number calls used for data

**P1 (only after all P0 boxes):**

- [ ] Batch: 10 pasted points show coloured pins and a sorted table; CSV export works
- [ ] Voice question in Hindi gets a grounded answer with citations
- [ ] The share link opens the saved analysis read-only
- [ ] District yield baseline shows when data.gov.in has the crop

## 13. Deployment

Deploy early (by hour 20) and redeploy often, so the deployed app gets tested, not just the local one. A team member must create the accounts and paste the keys; Claude Code writes the configs and the commands.

1. **Supabase:** create a free project → SQL editor → run `backend/sql/schema.sql` (the 3 tables in section 11) → copy the project URL and the service-role key.
2. **Gemini and Sarvam:** create the API keys; note the Gemini free-tier model name for `GEMINI_MODEL`.
3. **Backend on Hugging Face Spaces:**
   - Create a new Space with SDK **Docker** (blank template, free CPU hardware).
   - The Space's `README.md` must start with front matter including `sdk: docker` and `app_port: 7860`.
   - `Dockerfile`: `python:3.11-slim`, install the requirements, copy `app/`, then `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]`.
   - Settings → Variables and secrets: add every backend variable from section 2.
   - Push the `backend/` folder to the Space's git repo (or sync it with a GitHub Action). The URL looks like `https://<user>-<space>.hf.space`.
   - Check that `/health` returns `ok` and a test `/api/analyze` streams from the public URL.
4. **Frontend on Vercel:** import the GitHub repo → root directory `frontend` → framework preset Vite → env `VITE_API_URL` = the Space URL → deploy.
5. **CORS:** set `ALLOWED_ORIGINS` on the Space to the Vercel URL; redeploy the Space.
6. **Uptime:** add the free uptime monitor on `/health` (section 11).
7. **Smoke test** from a phone on mobile data: run the P0 acceptance list (section 12).

**Freeze rule:** after the 3 AM (1 Nov) gate, deploy only bug fixes, and re-run the smoke test after every deploy. Keep the last good deploy noted so you can roll back in one click on both platforms.

## 14. README, deck & video

The rules require a clean README with setup steps and an architecture diagram, a 2–3 minute live demo video, and a 5–7 slide deck. Judges read the README to check depth, so treat it as part of the product.

**README.md sections:**

1. One-line pitch + live URLs (app, backend health) + a screenshot of a farm in its risk colour.
2. The problem and who it's for (2–3 sentences).
3. Features, with the P0 list.
4. Architecture diagram (export the one from the PRD tab) + a numbered data flow from click to voice.
5. **Agent design:** the nodes, the fallback table, and how the validator stops invented numbers.
6. **Data provenance:** a table of every source, what it gives, its link and its licence/terms; a statement that the repo contains no mock data.
7. **Risk method:** the formulas from section 7 and a note that the thresholds are reviewable defaults.
8. Setup: prerequisites, `.env.example`, run backend, run frontend, run tests.
9. Limitations and roadmap (SMS/WhatsApp, IoT soil sensors, insurer API, field boundary drawing).
10. Team and who owns which part.

**Deck (5–7 slides),** following the organisers' recommended structure:

1. Title & team
2. The problem & real-world context (one cited statistic)
3. The solution & key features (one screenshot of the farm turning red + the voice moment)
4. Technical architecture & innovation (the diagram, the agent loop, the validator)
5. Why it's different + who pays (farmers free; FPOs, lenders, insurers as paying customers)
6. Roadmap & live demo summary

**Demo video (2–3 min):** record the deployed app (not localhost) following the demo script in the PRD tab. Show the trace streaming, the box turning red, the cloud-to-radar fallback, Hindi or Marathi voice, and one simulated outage. No cuts that hide loading time. Upload it as unlisted on YouTube or as a Loom, with the link set to public.
