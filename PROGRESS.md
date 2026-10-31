# KhetKavach — build progress

Source of truth: `SPEC.md` (PRD) + `BUILD_SPEC.md` (build spec). Build order = BUILD_SPEC §1.
If context is lost: re-read both specs and this file, then continue from "Next".

## Status

| Phase (BUILD_SPEC §1) | State |
| --- | --- |
| 1. Data spikes | in progress |
| 2. Fetchers + risk engine (F2–F6) | not started |
| 3. FastAPI + SSE + LangGraph agent (F7, F8, F10) | not started |
| 4. Frontend (F1, F12, F7 UI) | not started |
| 5. Sarvam translation + voice (F9) | not started |
| 6. Deploy files + user deploy steps | not started |
| 7. P1 (F11, F13, F14, F15) | not started |

## Log

### Step 0 — Setup (2026-10-31)
- Done: read SPEC.md + BUILD_SPEC.md fully; `git init -b main` in `forge/` (repo root = spec's `khetkavach/`);
  wrote `.env.example` and `.gitignore`; created Python 3.11 venv in `backend/.venv` with uv.
- Decision: fresh build in `forge/` (user chose this); `../forge2` is an older thinner attempt, used only as a hint.
- Decision: the PRD PDF is git-ignored (`*.pdf`); SPEC.md/BUILD_SPEC.md are committed as docs.
- Blocker (user is fixing): no `.env` yet → Gemini, Sarvam, Supabase spikes wait for it. Keyless spikes go first.
- Installed versions: fastapi 0.162.0, sse-starlette 3.6.0, langgraph 1.2.19, google-genai 2.34.0, httpx 0.28.1,
  pystac-client 0.9.1, planetary-computer 1.0.0, odc-stac 0.5.3, rioxarray 0.19.0, rasterio 1.4.4, numpy 2.4.6,
  Pillow 13.0.0, supabase 2.33.0, pydantic 2.14.2.

### VERIFY items from live docs (fetched 2026-10-31)
- Sarvam (docs.sarvam.ai API reference):
  - Translate `POST https://api.sarvam.ai/translate`, header `api-subscription-key`; body `input`, `source_language_code`,
    `target_language_code`, `model` = `sarvam-translate:v1` (Sarvam-Translate; max 2000 chars/request, formal mode only),
    `numerals_format` = `international` (default) | `native`. Response `translated_text`.
  - TTS `POST https://api.sarvam.ai/text-to-speech`; **model id is `bulbul:v4-flash`** (no plain `bulbul:v4`); `text` is one
    string, max 2500 chars; `language_code`; `speaker` names `<name>_<lang>_<style>` (e.g. `ritu_hi_conversation`);
    `pace` 0.5–2.0; `speech_sample_rate` default 22050; `output_audio_codec` default `wav`; response `audios` = list of
    base64 WAV. v4-flash languages: hi, en, bn, gu, kn, mr, pa, ta, te (no ml/od) → matches the spec's 9 languages.
  - STT `POST https://api.sarvam.ai/speech-to-text` multipart `file`, `model` = `saaras:v4`, `language_code` = `unknown`
    for auto-detect; ≤ 30 s per REST request; response `transcript`, `language_code`.
  - Errors: 402 = out of credit (don't retry), 429 = rate limit, 403 = bad key. Bulbul v4 Flash ₹1/1000 chars,
    translate ₹2/1000 chars.
- Gemini (ai.google.dev docs, updated 2026-10-28): free-tier stable models with Gemini-3 tool calling + structured output:
  `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`. 2.0 models shut down; 2.5 restricted to existing users.
  Docs now show the Interactions API; `generate_content` + `response_schema` must be confirmed by the live spike.
- Open-Meteo docs: daily `precipitation_sum`, `precipitation_probability_max`, `temperature_2m_max`, `temperature_2m_min`,
  `et0_fao_evapotranspiration`; hourly `soil_moisture_3_to_9cm`, `soil_moisture_9_to_27cm` (m³/m³) all exist;
  `forecast_days` 0–16, `past_days` 0–92. Free API: 10,000 calls/day; requests longer than 2 weeks count as multiple
  calls (a 20-year archive call is heavy → must be cached 30 days as the spec says).
- Nominatim policy: max 1 req/s, identifying User-Agent, results must be cached.
- Planetary Computer + NASA POWER docs pages are client-rendered → verify from STAC collection JSON and live spikes.

### Step 1 — Phase 1 data spikes (keyless sources verified live, 2026-10-31)
- Done: `backend/scripts/spike_planetary.py`, `spike_openmeteo.py`, `spike_nasa_power.py`, `spike_nominatim.py` run
  against the live APIs for the Nashik test point (20.0, 73.79). `spike_gemini.py` and `spike_sarvam.py` are written
  and will run as soon as `.env` exists.
- Decision: Phase 2 (fetchers + risk engine) only uses keyless sources, so it starts now; the Gemini spike runs before
  any Phase 3 agent code and the Sarvam spike before any Phase 5 code. Supabase connectivity is checked with `.env`.
- VERIFY Sentinel-2 (Planetary Computer, anonymous + `sign_inplace` works): 6 scenes in 2026-10-01..31 (cloud < 80%),
  newest `S2C_MSIL2A_20261030T052941_R105_T43QCC_20261030T101000` cloud 11.3%. Property `s2:processing_baseline`
  is a **string** `'05.13'`. Asset keys B02 B03 B04 B08 B11 SCL present. A 500 m box loads as 51×52 px at 10 m (UTM 43N).
- VERIFY reflectance offset: the scene's ESA `product-metadata` XML says `BOA_ADD_OFFSET = -1000` for every band and
  `BOA_QUANTIFICATION_VALUE = 10000` → reflectance = (DN − 1000) / 10000, exactly as the spec says. Raw B02 min = 1208.
- VERIFY Sentinel-1: `sentinel-1-rtc` is accessible anonymously (3 scenes in 24 days, assets `vv`,`vh`, float32
  **linear** gamma0, nodata −32768; Nashik VV median 0.513 → −2.90 dB, VH 0.0706 → −11.51 dB). `sentinel-1-grd` also
  accessible but values are uncalibrated DN amplitude (VV median 457) → only usable as relative change (20·log10).
- VERIFY Open-Meteo forecast: HTTP 200 in 1.26 s; daily keys exactly `precipitation_sum`, `precipitation_probability_max`,
  `temperature_2m_max`, `temperature_2m_min`, `et0_fao_evapotranspiration`; hourly `soil_moisture_3_to_9cm`,
  `soil_moisture_9_to_27cm` (m³/m³). `past_days=30` + `forecast_days=16` → 46 daily rows (2026-10-01 → 2026-11-15);
  index 30 = today. Hourly soil moisture had 18 trailing nulls → code must skip nulls.
- VERIFY Open-Meteo archive: 2006-01-01..2025-12-31 in **one** call, HTTP 200 in 1.72 s, 7305 days, 0 nulls.
- VERIFY NASA POWER: HTTP 200 in 2.17 s; path `properties.parameter.PRECTOTCORR` / `.T2M_MAX` as `{"YYYYMMDD": value}`;
  units mm/day and C; `header.fill_value` = −999.0; `time_standard` LST; 7305 values each.
- VERIFY Nominatim: reverse (zoom 14) → `address.country_code` = `in`, `state_district` = "Nashik District",
  `state` = "Maharashtra". Arabian Sea point (18.5, 70.0) → `{"error": "Unable to geocode"}` (no address).
  Pakistan point → `country_code` `pk`. Search "Niphad" with `countrycodes=in` → 4 results with lat/lon strings.
- Next: commit, then Phase 2 source modules + risk engine + unit tests.

### Step 2 — Phase 2: fetchers + risk engine (F2–F6) — DONE
- Done: `app/config.py`, `app/risk.yaml` (every threshold/weight/stage table with origin comments), `app/models.py`
  (§5 schemas), `app/cache.py` (memory + Supabase PostgREST), `backend/sql/schema.sql`, `app/sources/common.py`
  (IST time, 500 m box, 8 s timeout, 2 retries 0.5 s/1.5 s on timeout/429/5xx → `SourceUnavailable`),
  `sources/geocode.py`, `weather.py`, `baseline.py`, `satellite_optical.py`, `satellite_radar.py`,
  `engine/overlay.py`, `engine/crops.py`, `engine/risk.py`; tests `test_risk.py`, `test_overlay.py`,
  `test_sources_live.py` (`@pytest.mark.live`).
- Tests: `pytest` → 27 passed (unit). `pytest -m live` → 6 passed in 30 s (forecast, ERA5, NASA POWER, Nominatim
  reverse/reject/search, Sentinel-2, Sentinel-1 RTC).
- Decision: Supabase is reached through its REST API (PostgREST) with httpx instead of supabase-py, so every cache
  call is async and has a timeout; same tables/keys as §11. Without Supabase keys the cache runs in memory only.
- Decision: the baseline caches the raw 20-year daily history per 0.05° cell (fetched for the cell centre) for 30 days
  and recomputes today's windows on each run; the anomaly `rain_past30_anomaly_pct` needs the forecast's past-30-day
  rain, so it is computed in the risk engine and cited as a `score_risk` output (with both inputs cited too).
- Decision: optical results (now + last year + overlays) are cached together for 24 h per 0.002° cell; the separate
  30-day last-year cache entry from §11 was folded into this to keep the arrays and PNGs consistent.
- Decision: rasters are loaded on a ~10 m lat/lon grid (EPSG:4326, 0.00009°) so overlay PNG bounds align exactly with
  the Leaflet map. PNGs stay at native resolution (≈51×52 px, 1.5–7.5 KB each); the browser upscales pixelated.
- Decision: confidence also steps down when there is no satellite evidence at all (in addition to §7's four reasons),
  per the PRD guardrail "the confidence badge drops when evidence is missing".
- Decision: radar change overlay bins ±1/±3 dB (in risk.yaml) — same colours as the ΔNDVI ramp.
- Decision: a box ≥ 50% water in its least-cloudy scene raises `NotFarmland` instead of `TooCloudy`, so the trace never
  blames cloud for a river; built-up/water note when NDVI median < 0.1 now and last year.
- VERIFY (live, Nashik 20.0, 73.79, 2026-10-31): forecast rain_next16 8.6 mm, max 3-day 7.3 mm, dry run 13 days,
  ET0 72.9 mm, deficit 64.3 mm, soil root 0.246 m³/m³, past-30 rain 2.5 mm, rain prob next 7 d max 82%.
  ERA5 normal (20 yrs 2006–2025): past-30 60.3 mm, next-16 12.3 mm, tmax mean 29.5 °C. NASA POWER: 80.4 / 13.7 / 28.4.
  Sentinel-2: scene 2026-10-30 (S2C…T43QCC), box clear 1.0, NDVI 0.125, NDMI −0.104; last year 2025-11-06 NDVI 0.136,
  NDMI −0.06; ΔNDVI −0.011, ΔNDMI −0.044; optical pipeline 11 s. Sentinel-1 RTC: 2026-10-24 VH −11.51 dB vs
  2025-10-22 −11.25 dB (same orbit) → Δ −0.26 dB, 9 s; GRD fallback 14 s. Overlays visually checked (true colour
  shows the built-up Nashik test point; NDVI matches park patches).
- Next: Phase 3 — FastAPI + SSE + LangGraph agent + validator. Needs the Gemini spike first (`.env`).

### Step 3 — Phase 3: FastAPI + SSE + LangGraph agent (F7, F8, F10) — DONE (LLM path awaiting key)
- Done: `app/events.py`, `app/agent/tools.py` (catalogue, fallback table, executor, demo `fail`, evidence flattening,
  risk inputs with citations), `agent/validator.py`, `agent/prompts.py` (write prompt verbatim from §8),
  `agent/llm.py` (google-genai: function calling for plan/recover, `response_json_schema` for write, 15 s timeout,
  budget 4 calls), `agent/graph.py` (LangGraph: check_location → plan → gather → check → recover ⟲ ≤2 → score →
  write → validate (⟲ rewrite once) → localise → save), `app/main.py` (`/health`, `/api/meta`, `/api/search`,
  `/api/analyze` SSE with 15 s ping, `/api/analysis/{id}`; errors always `{code, message, retryable}`).
- Tests: `pytest` → 37 passed (risk, overlay, validator incl. invented number / bad citation / out-of-window date,
  422 input errors, /health, ocean stream). `pytest -m live tests/test_api.py` → 6 passed: full run event order
  (run_started first, run_completed last, saved analysis readable) and each demo control
  (satellite, forecast, baseline, llm, sarvam) ends in run_completed with a partial result.
- Decision: events are streamed with LangGraph's custom stream writer (`stream_mode=["custom","values"]`), so tool
  rows appear the moment each parallel call starts/finishes. Overlays are streamed but not repeated in the trace.
- Decision: nodes are deadline-aware (45 s): gather keeps 9 s in reserve for score/write/save and cancels slow calls
  with `RUN_DEADLINE`; LLM calls shrink their timeout near the deadline. An outer 55 s guard emits a retryable error.
- Decision: added a `note` event (warnings such as "Plan generated from rules", land-cover note) and `/api/meta`
  (languages in native script, crops, whether demo controls are on) — small additions the UI needs.
- Decision: if Nominatim is down, a point inside India's rough bounding box is analysed as "Unnamed place"
  (coordinates label); outside it is rejected.
- Decision: GDAL HTTP timeout 6 s + 2 retries per blob read (a single stalled read once used the whole 25 s budget
  in testing; the agent recovered, but now a stall fails fast and retries).
- Bug fixed: validator read "6 Nov, 1,500" as the date 6 Nov 1500 → years now restricted to 19xx/20xx.
- VERIFY (live run, Nashik 20.0, 73.79, wheat sown 2026-10-08 → crown-root initiation): Drought 92 (High),
  Excess rain 13, Heat 0; top driver "Evaporation will exceed rain by 64.3 mm over the next 16 days" cited to
  c2.water_deficit_mm; rule-based plan, validator "6 numbers checked, 0 rejected". Uncached run 9.3 s
  (S2 search 1.8 s, SCL checks 1.9 s, last-year 2.5 s, band reads 2.7 s).
- Still open: Gemini plan/recover/write calls are coded against the installed SDK but not yet run live (no
  GEMINI_API_KEY). Run `backend/scripts/spike_gemini.py` the moment `.env` exists.
- Next: Phase 4 frontend.

### Step 4 — `.env` arrived: Gemini + Sarvam spikes, LLM path verified, fixes (Phases 1 and 3 now complete)
- VERIFY Gemini (`spike_gemini.py`, live): key sees `gemini-3.5-flash-lite`, `gemini-3.8-flash`, `gemini-3.6-flash` …
  With `gemini-3.5-flash-lite` + `thinking_level="low"`: function calling (mode ANY, AFC disabled) returned tool calls in
  1.51 s; `response_json_schema` JSON output in 1.59 s. `GEMINI_MODEL=gemini-3.5-flash-lite` kept.
  Observed: the model invents out-of-enum args (window_days 60) → the app clamps args to the catalogue.
- VERIFY Sarvam (`spike_sarvam.py`, live): translate `sarvam-translate:v1` + `numerals_format=international` →
  hi-IN 1.08 s, mr-IN 0.86 s, numbers 6/9/48 kept as 0-9 digits. TTS `bulbul:v4-flash`, all 9 voices valid
  (simran_en_narration, ritu_hi_conversation, neha_mr_narration, arnab_bn_conversation, pooja_gu_conversational,
  chaitra_kn_narration, harpreet_pa_narration, vijay_ta_narration, kavitha_te_narration): response keys
  `request_id`, `audios` (base64 WAV, 1 ch, 22050 Hz, 16-bit), 0.43–0.62 s each. STT `saaras:v4` +
  `language_code=unknown` on that Hindi audio → transcript "सिंचाई करें।", `language_code` hi-IN,
  `language_probability` 0.677.
- VERIFY Supabase: REST reachable, service-role key (`sb_secret_…`) accepted; tables not created yet
  (PGRST205) → user must run `backend/sql/schema.sql`. Cache stays memory-only until then.
- VERIFY Nominatim: the `.env` User-Agent still had the template contact `…@example.com` → HTTP 403
  "Access denied"; Nominatim blocks placeholder contacts. Config now ignores a placeholder and sends
  `KhetKavach/1.0 (Forge26 hackathon)` (HTTP 200). User asked to set a real email.
- Bug fixed (found live): on rewrite Gemini wrote `c2.water_deficit_mm mm` inside the text, which hid numbers from
  the validator. Fix: FORMAT_NOTE in the write prompt (numbers in text, references only in `citations`) and the
  validator now rejects any `cN.field` written in text (new unit test).
- Change: `run_started` is now emitted immediately (place null) and geocoding is the first trace row `geocode`
  (c0) → first event at 0.0 s (was 2.2 s), meeting "trace within 1 s". Supabase cache writes run in the background.
- VERIFY live run with Gemini (Nashik 20.0, 73.79, wheat sown 2026-10-08, uvicorn + curl): plan by LLM in 1.6 s;
  S2 13.2 s; Drought 78 High / Excess 13 / Heat 0; LLM plan 3 actions; validator "9 numbers checked, 0 rejected";
  total 19.2 s. Earlier run showed the rewrite loop working ("1 number(s) rejected → asking for a rewrite").
- Tests: 38 unit/API passed; 12 live passed (64.7 s).

### Step 5 — Phase 4: frontend (F1, F12, F7 UI) — DONE locally
- Done: `frontend/` React 18 + Vite 6 + TypeScript + Tailwind 3 + shadcn-style components on Radix (tabs, tooltip) +
  react-leaflet 4 + Recharts 2. Files: `lib/api.ts` (types mirroring models.py), `lib/sse.ts` (EventSource → run
  state; reconnect once, then "Connection lost — Retry"), `components/MapView.tsx` (Esri/OSM, click-to-pick,
  fly to zoom 16 in 1.2 s, analysis box grey dashed pulse → risk colour with 800 ms fade, High pulses 3×, label
  "Moderate drought risk · 54", evidence overlays in their own pane at 70% opacity, layer control), `Legend.tsx`,
  `BeforeNowSlider.tsx`, `SearchBox.tsx`, `TracePanel.tsx`, `RiskCard.tsx`, `ActionPlan.tsx`, `EvidencePanel.tsx`,
  `SourceBadge.tsx` (source chips + citation tooltips), `LanguagePicker.tsx`, `DemoMenu.tsx` (Shift+D),
  `pages/Home.tsx` (idle/running/done/partial/rejected/error states, crop + sowing date, mobile stack),
  `App.tsx` (header, "Waking up the server…" 20 s /health retry). `vercel.json` added.
- Backend change: `tool_succeeded` now carries `kind` + `result` (tool output without overlay PNGs) so the Evidence
  chart has the real series.
- VERIFY (Chrome, localhost): search "Niphad" → 4 hits in Nashik District; picking one streamed the trace live
  (geocode 1.1 s, LLM plan, forecast 1.7 s, ERA5 3.2 s, Sentinel-2), box turned amber with label
  "Moderate drought risk · 54"; ΔNDVI overlay + legend "Scene 30 Oct 2026 · 2.5% hidden"; slider labels
  6 Nov 2025 ↔ 30 Oct 2026; Risk card Drought 54 / Excess 11 / Heat 0 with citation chips; Plan tab 4 LLM actions
  with chips; Evidence chart 16 days + ERA5 normals, NDVI 0.236 vs 0.209 last year.
- Fixes found in browser: SearchBox was not mounted; Recharts line animation made lines look truncated (disabled);
  rain axis label clipped; running outline thickened to 3 px.
- Build: `npm run build` OK; gzipped JS ≈ 251 KB + CSS 11 KB (budget 500 KB).
- Decision: `.env.example` had real keys pasted into it (they are in earlier local commits; user said to leave the
  history as is). The working file is now the blank template; keys live only in `.env`. Not pushed to GitHub yet.
- Next: Phase 5 — `/api/translate`, `/api/tts`, Sarvam module, VoicePlayer, translate-on-language-change.

### Step 6 — Phase 5: Sarvam translation + voice (F9) — DONE locally
- Done: `backend/app/sources/sarvam.py` (translate item-by-item with `sarvam-translate:v1` + international numerals;
  number check after translation → line kept in English with `english_fallback`; TTS `bulbul:v4-flash`, one voice
  per language, pace 0.95, summary + top 3 actions ≤ 1,500 chars, chunking + WAV join for > 2,500 chars; STT
  `saaras:v4` helper for P1; permanent media cache keyed by sha256(model+lang+voice+text)).
  Endpoints `POST /api/translate`, `POST /api/tts` (503 `TRANSLATION_UNAVAILABLE` / `VOICE_UNAVAILABLE`; honour the
  run's `sarvam` demo control). Frontend `VoicePlayer.tsx` (play/pause, progress, language name, "Voice by Sarvam",
  disabled + tooltip while generating), translate-on-language-change in `Home.tsx`, `ActionPlan` shows the
  translation with "(English)" tags.
- Tests: 41 unit passed (incl. number-survival, speech text, WAV join); live `test_translate_and_tts_live` passed.
- VERIFY (Chrome): run with हिन्दी selected → Hindi summary/actions; one action kept in English because
  "0.305 m3/m3" did not survive translation (correct per §9). Switching to मराठी after the run → Marathi
  translation (16, 60.9, 3.5, 60.8, 94.2 preserved) and a 45.7 s Marathi WAV from one Sarvam call.
- Bugs fixed: `/api/tts` 404 was a stale server (started before the route existed) → dev server now runs with
  `--reload`; React StrictMode fired TTS twice → in-flight guard in VoicePlayer.
- VERIFY Supabase: tables now exist (user ran schema.sql) → `/health` supabase "ok"; analyses survive restarts.
- Next: pick the 3 quick-farm chips with live runs, then the P0 acceptance checklist (§12), then deployment files.
