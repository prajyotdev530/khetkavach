# KhetKavach — Product Requirements Doc

Forge '26 · Theme 2 · Predictive Climate & Micro-Location Yield Engine

Oct 31, 2026 · @Prajyot

## Summary

**KhetKavach** is an AI agent that lets anyone click a farm in India and get, in about 30 seconds, a live 14-day forecast of drought, unseasonal-rain and heat risk, plus an action plan read aloud in the farmer's language. Every number is traced to a satellite pass, a weather model or an official dataset.

- **Track:** Theme 2, Climate, Resource Infrastructure & Global Supply Resilience
- **Problem:** Predictive Climate & Micro-Location Yield Engine
- **Deadline:** plan for **1 Nov 2026, 6:00 PM IST**. The Unstop stage timeline shows this time; the details text says 11:59 PM. Confirm on Launchpad.

**Why this wins.** The ranking is overall across both tracks, so we win on depth and demo, not on a quiet track:

1. **Depth (20 pts).** It's a real geospatial pipeline, which the rubric names as its own example of depth.
2. **Agentic (25 pts).** The agent plans its tool calls, recovers when an image is cloudy or a source fails, and cites every number.
3. **Impact and USP (25 pts).** It gives farm-level, not district-level, risk with voice advice in Indian languages. The same score serves farmers, agri-lenders and crop insurers.
4. **Demo (30 pts).** A judge clicks any farm, on any day, and watches the agent work live. It doesn't depend on the weather cooperating.
5. **Zero disqualification risk.** All inputs are real, official or open data. No mock data anywhere.

**For Claude Code:** the full implementation spec (API contracts, formulas, UI details, tests, deployment) is in Build spec.

## Problem & target users

Weather advice in India is mostly issued at district level and in text. A single district can span very different rainfall, soil and crop conditions, so a farmer gets advice that may not fit their own field, often too late and in a language or format they don't use.

**The gap we close:** risk at the level of one farm, predicted ahead, explained by voice in the farmer's language, with reasons shown.

| User | Pain today | What KhetKavach gives them |
| --- | --- | --- |
| Smallholder farmer (primary) | Generic district advice; no early warning for dry spells, heat at flowering or unseasonal rain | Farm-specific 14-day risk + 3–5 concrete actions, spoken in their language |
| FPO / Krishi Vigyan Kendra field officer | Can't monitor hundreds of member farms | Batch risk view across many plots, sorted by risk |
| Agri-lender / crop insurer (B2B) | Crop-risk checks need field visits; slow and costly | An explainable farm risk score with satellite evidence, usable for underwriting and claims triage |

**Timing:** November is rabi sowing season (wheat, mustard, gram), so live advice is useful the day judges test it.

We have not looked up statistics on farmer losses or advisory reach. Any figure that goes in the deck needs a cited source.

## Solution & core user flow

The user picks a farm, and an agent gathers evidence, scores the risk and writes a cited plan, while the screen shows each step as it happens.

1. **Pick a farm.** Click the map, search a village, or say it by voice (Saaras speech-to-text). Optionally choose the crop and sowing date.
2. **The agent plans.** It decides which evidence it needs and shows that plan in a live "agent trace" panel.
3. **It gathers evidence**, each step with a source tag:
   - crop health and water stress from Sentinel-2 (vegetation and moisture indices, now vs the same weeks last year)
   - Sentinel-1 radar instead, if the optical image is cloudy
   - the 16-day forecast and soil moisture from Open-Meteo
   - the historical normal from ERA5 and NASA POWER, to compute anomalies
4. **It scores risk.** Separate scores for drought, excess or unseasonal rain, and heat stress, each with a 0–100 score, a level and its key drivers.
5. **It writes the plan.** 3–5 dated actions tied to the crop stage (for example "irrigate before 6 Nov; dry spell of 9 days forecast"), each number cited.
6. **Language and voice.** Sarvam translates the plan and reads it aloud in the selected language.
7. **Share.** A link to the risk card, with an optional SMS/WhatsApp-style text for a field officer to forward.

## Features

All P0 items must work end to end on the live URL by hour 24. P1 items are added only when P0 is stable. P2 items go in the roadmap slide, not the build.

| # | Feature | Priority | Done when |
| --- | --- | --- | --- |
| F1 | Interactive map: street/satellite toggle, click-to-pick farm, village search, 500 m analysis box (Leaflet, Nominatim, Esri imagery) | P0 | Street/satellite toggle works; a click or search drops a pin, draws the analysis box and returns the village/district name |
| F2 | Satellite crop-health fetcher (Sentinel-2 via Planetary Computer) | P0 | Returns NDVI/NDMI now + same window last year for a \~500 m box, with scene date and cloud % |
| F3 | Cloud fallback to Sentinel-1 radar | P0 | Agent switches to radar automatically when the image is more than 40% cloudy, and logs why |
| F4 | Weather + soil fetcher (Open-Meteo forecast, 16 days) | P0 | Daily rain, max temperature, evapotranspiration and soil moisture for the point |
| F5 | Historical baseline (Open-Meteo ERA5 + NASA POWER) | P0 | Rainfall and temperature anomaly vs a 10–20 year normal for the same dates |
| F6 | Risk engine (drought / excess rain / heat) | P0 | Three 0–100 scores, a level and the top drivers, computed in code, not by the LLM |
| F7 | Agent orchestrator with live trace | P0 | The trace panel shows plan, tool calls, retries and fallbacks as they happen |
| F8 | Cited action plan | P0 | 3–5 dated actions; every number carries a source tag; a validator rejects numbers not found in tool outputs |
| F9 | Sarvam translate + voice | P0 | Plan in Hindi and Marathi (plus more), with a play button (Bulbul v4) |
| F10 | Graceful degradation | P0 | Any source down leads to a partial result with a "data unavailable" badge, never a crash |
| F11 | Voice question in (Saaras STT) | P1 | Farmer asks "should I irrigate this week?" in Hindi and gets a grounded answer |
| F12 | Crop-health map overlay (the farm turns red/yellow/green) + before/now slider | P0 | The analysis box is coloured from the live Sentinel-2 crop-health values (reusing F2's data), with a legend and scene date; a slider compares now vs the same time last year |
| F13 | Multi-farm batch view (FPO / lender) | P1 | Paste 5–20 locations; they appear as red/yellow/green risk pins on the map plus a table sorted by risk, exportable as CSV |
| F14 | Crop-yield baseline from data.gov.in district stats | P1 | Shows the district's historical yield for the chosen crop beside the risk |
| F15 | Shareable risk-card link | P1 | A permanent URL per analysis, read back from the database |
| F16 | SMS/WhatsApp delivery, IoT soil sensors, insurer API, draw-your-own field boundary | P2 | Roadmap only |

## How we score on the rubric

Every rubric line has a feature and a demo moment that proves it. Judges should never have to take our word for something.

| Pillar (pts) | What judges look for | How we prove it | Features |
| --- | --- | --- | --- |
| Engineering depth (20) | Beyond a wrapper; custom pipelines; clean, modular code; low latency | Real raster processing of satellite imagery, an anomaly engine and a typed tool layer. One module per data source, async parallel fetches, a cache. Target under 30 s per analysis, under 3 s when cached | F2–F7 |
| AI reasoning & agentic (25) | Plans multi-step tool calls, handles errors, self-corrects; accuracy, guardrails, citations | A visible plan, then tool calls, then a cloud or outage fallback, then re-planning. Numbers are computed by tools, never by the LLM, and a validator checks every cited figure. Every output line has a source tag | F3, F7, F8, F10 |
| Impact & USP (25) | Real value; differs from chatbots and standard software; scales | Farm-level, not district. Ahead of time, not after. Voice in Indian languages. One engine serves farmer, FPO and lender (B2B revenue path). Works anywhere in India with no new hardware | F6, F9, F13 |
| Live demo & robustness (30) | Runs live without crashing; handles bad input, missing data, network failures | Judges pick any farm. We show an ocean click (rejected politely), a cloudy scene (radar fallback) and a source kill-switch (partial result), all live | F1, F3, F10 |

**Audience Favourite (₹20,000):** the Marathi or Hindi voice playback and the before/now satellite view are the moments a non-technical audience remembers.

**Explain-ability check (rule 6):** each member owns one layer but must be able to walk through the full data flow. Do a mock Q&A at hour 34.

## Data sources & no-dummy-data compliance

Every number on screen comes from a live API or an official open dataset, fetched at request time and shown with its source and timestamp. Total cost is ₹0: the only metered service is Sarvam, covered by its ₹100 free credit.

| Data | Source | Key | Status / note |
| --- | --- | --- | --- |
| Optical satellite (NDVI, NDMI) | [Microsoft Planetary Computer](https://stacspec.org/en/tutorials/reading-stac-planetary-computer/), Sentinel-2 L2A | None | Free STAC API; reading needs no account |
| Radar satellite (cloud fallback) | Planetary Computer, Sentinel-1 RTC | None | Used only when optical cloud cover exceeds 40% |
| Forecast, soil moisture and soil temperature | Open-Meteo Forecast API | None | 16-day daily data |
| Historical normal | Open-Meteo Historical (ERA5) + NASA POWER | None | NASA POWER doubles as a backup source |
| Soil properties (optional) | ISRIC SoilGrids | None | [REST API currently paused](https://www.isric.org/explore/soilgrids); read the raster files directly or skip |
| District crop yield (P1) | data.gov.in crop production statistics | Free key | Official Indian dataset; check the resource has its API enabled |
| Place names | Nominatim (OpenStreetMap) | None | 1 request per second; cache results |
| Translation, text-to-speech, speech-to-text | [Sarvam AI](https://docs.sarvam.ai/api/getting-started/models.md): Sarvam-Translate, Bulbul v4, Saaras v4 | Team key | ₹100 free credit; cache audio |
| Agent LLM | Gemini API free tier (or another tool-calling model) | Team key | Sarvam's docs don't confirm tool calling, so it handles language only |

**Compliance rules for the team:**

- No JSON fixtures in the repo, not even for tests. Tests call the live APIs or use recorded responses kept outside the app path.
- The cache stores real responses with their fetch time. The UI shows "fetched 3 min ago" and never presents cached data as live.
- No hardcoded thresholds disguised as data. Risk thresholds are documented constants in config with a comment saying where each comes from.
- Mandi prices are left out: the data.gov.in mandi resource currently has no live API.

## Technical architecture & stack

A Python backend runs the agent and the geospatial work. A light React frontend streams the agent's steps live.

&#91;embedded content: system architecture · web app, backend, 6 external sources\]

The LLM never produces a number on its own: tools fetch the data, the risk engine computes the scores, and the validator rejects any figure in the plan that isn't in a tool output.

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | React + Vite + Leaflet + Tailwind, on Vercel | Fast map UI; Server-Sent Events show the agent trace live |
| Backend | FastAPI + LangGraph, in a Docker container on Hugging Face Spaces (free CPU tier) | Python is needed for the raster libraries; a state graph scores as "complex state graph" depth |
| Geospatial | pystac-client, planetary-computer, odc-stac / rioxarray, numpy | Reads only the small window around the farm, which keeps it fast |
| Storage | Supabase Postgres | Cache of real responses with fetch time, plus shareable risk-card links |
| AI | Gemini API free tier (tool calling) for the agent; Sarvam for translation, text-to-speech and speech-to-text | Reliable tool calls + strong Indian-language voice |

## Agent design

The LLM decides what to fetch and how to explain it. Deterministic code does the math. A validator checks the LLM's output before anyone sees it.

**Tools the agent can call** (typed inputs and outputs, each returning `source` and `fetched_at`):

| Tool | Returns | On failure |
| --- | --- | --- |
| `geocode(lat, lon)` | village, district, state | fall back to coordinates only |
| `get_optical_index(lat, lon, window)` | NDVI, NDMI, scene date, cloud % | retry with a wider date window, then hand over to radar |
| `get_radar_index(lat, lon, window)` | backscatter (VV/VH) change vs last year | mark crop-health evidence as unavailable |
| `get_forecast(lat, lon)` | 16 days of rain, temperature, evapotranspiration, soil moisture | retry once, then use NASA POWER recent data and flag "no forecast" |
| `get_baseline(lat, lon, dates)` | 10–20 year normal for rain and temperature | switch between ERA5 and NASA POWER |
| `score_risk(evidence, crop, stage)` | 3 scores + drivers | pure code, never fails silently |
| `translate(text, lang)` / `speak(text, lang)` | text / audio URL | show the English plan plus a "voice unavailable" note |

**The agent loop** (LangGraph state graph):

1. **Plan.** Read the request and list the evidence needed for this crop and stage.
2. **Act.** Call independent tools in parallel.
3. **Check.** Is each result present, fresh and usable (cloud %, null values, out-of-India location)?
4. **Recover.** On a failed check, pick a fallback tool or widen the window, at most 2 retries per tool. Every recovery is logged to the trace.
5. **Score.** Call `score_risk` once the minimum evidence is in.
6. **Write.** The LLM drafts the plan with structured output: actions, each with `cites: [tool_call_id]`.
7. **Validate.** Every number in the draft must match a tool output (with a small tolerance). If not, regenerate once, then drop that line.
8. **Localise.** Translate and generate voice, using cached results when available.

**Guardrails:**

- Refuse locations outside India or over water with a clear message.
- The confidence badge drops when evidence is missing (for example "radar only" or "forecast unavailable").
- No chemical brand or dosage advice; point to the local KVK/agri officer for those.
- Timeouts: 8 s per tool, 45 s for the whole run, then return a partial result.

## Demo script (3 minutes) & finale pitch

The video must be a real screen recording of the live deployed app, with no cuts that hide loading. The rules disqualify pre-recorded mockups.

| Time | On screen | What we say |
| --- | --- | --- |
| 0:00–0:20 | Map of India, then a zoom to a wheat farm | "District advice doesn't fit one field. KhetKavach gives risk for this field." |
| 0:20–1:10 | Click the farm; the agent trace streams its plan, parallel fetches and scene dates | "Live Sentinel-2 from 4 days ago, a 16-day forecast, and a 20-year baseline." |
| 1:10–1:40 | Risk card: 3 scores, drivers, before/now satellite view | "Drought risk 72: rain 48% below normal and soil moisture falling." (use the real numbers on screen) |
| 1:40–2:05 | Click a cloud-covered farm; the trace shows "cloud 85% → switching to radar" | "It noticed and corrected itself, with no human involved." |
| 2:05–2:35 | Hindi or Marathi plan with voice playback | Let the audio play for about 8 seconds. |
| 2:35–3:00 | Ocean click (polite refusal), then a source kill-switch (partial result + badge) | "It doesn't crash and it doesn't make things up. Every number links to its source." |

**Finale pitch (5–7 slides):** 1) Title & team, 2) Problem with one cited statistic, 3) Solution + live demo, 4) Architecture & agent loop, 5) Why it's different (farm-level, ahead of time, voice, cited), 6) Who pays and how it scales (FPOs, lenders, insurers) + roadmap, 7) Ask/close.

**Pick demo farms in advance:** 2 clear-sky farms with an interesting risk (check them at hour 30) and 1 known cloudy area. Keep their links ready, but still click them live.

## Build plan & roles

We have about 37 hours to a 4 PM submission on 1 Nov. The one gate that matters is P0 live on the deployed URL by 3 AM on 1 Nov.

&#91;embedded content: build plan · 5 phases, 5 gates, IST\]

Don't move to the next phase until its gate passes. If a gate slips by more than 2 hours, cut a P1 item rather than a P0 one. Rotate sleep in 4-hour shifts so someone is always building.

| Member | Owns | Features |
| --- | --- | --- |
| A: Geo & data lead | Satellite + radar fetchers, baseline, risk engine, data-provenance README section | F2, F3, F5, F6, F12, F14 |
| B: Agent & backend lead | FastAPI, LangGraph loop, tool layer, validator, LLM + Sarvam, backend deploy | F4, F7, F8, F9, F10, F11 |
| C: Frontend & demo lead | Map, agent-trace panel, risk card, voice player, batch view, deck, video | F1, F13, F15 + submission |

With 2 members, A also takes the risk engine and the deck, and B also takes the frontend. Use a ready-made UI kit (shadcn/ui) to save time. Everyone joins the hour-34 mock Q&A.

## Risks & mitigations

The two things that could cost us the win are a slow or crashing demo and anything that looks like fake data. Everything below targets those two.

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Satellite fetch is slow (large raster files) | Demo drags past 30 s | Read only a small window around the farm (cloud-optimized reads), limit the search to the last 30 days, cache by tile and date |
| A judge accuses us of mock data | Instant disqualification | No fixtures in the repo; source + timestamp on every number; README section "Data provenance" |
| Planetary Computer or Open-Meteo is down at judging time | Demo breaks | Backup source per signal (NASA POWER); partial results with badges; cached real responses labelled with fetch time |
| LLM invents numbers | Loses accuracy points | Numbers come only from tools; validator; structured output with citations |
| Sarvam credits run out | Voice demo fails | Cache translations and audio by text hash; budget about ₹50 for testing; English fallback |
| Free hosting sleeps (cold start) | First click takes 60 s in front of judges | Hugging Face Spaces free CPU only sleeps after long inactivity; still add a keep-alive ping and open the app 5 min before judging |
| Scope creep | Nothing finished | Hard freeze on P0 at hour 24; P1 only on a green build |
| A member can't explain part of the code (rule 6) | Disqualification on questioning | Each member walks through the whole flow at hour 34; README architecture section written by the team |
| Deadline ambiguity (6 PM vs 11:59 PM) | Missed submission | Submit at 4 PM on 1 Nov; confirm the real deadline on Launchpad today |

## Submission checklist

Aim to submit everything by **1 Nov, 4:00 PM IST**, two hours before the earlier deadline.

- [ ] Theme 2 and the project name "KhetKavach" entered on Launchpad
- [ ] Problem statement: target issue and context + target audience (from the Problem section)
- [ ] Solution description: overview + architecture (core stack, models, datasets, system design)
- [ ] Live URL works from a phone on mobile data, in incognito
- [ ] 2–3 minute demo video of the live app (YouTube unlisted or Loom), link set to public
- [ ] Public GitHub repo: README with setup steps, architecture diagram, data provenance, `.env.example` (no real keys committed)
- [ ] 5–7 slide deck, link set to anyone-with-link
- [ ] Every member has done the mock Q&A on the full data flow
- [ ] API keys rotated or limited after the event if the repo ever exposed them

## Sources

- [Forge '26 listing on Unstop (prizes, timeline, format)](https://unstop.com/hackathons/forge-26-indias-biggest-gen-ai-buildathon-nxtwave-launchpad-1783707)
- [Sarvam AI models](https://docs.sarvam.ai/api/getting-started/models.md)
- [ISRIC SoilGrids (REST API paused)](https://www.isric.org/explore/soilgrids)
- [data.gov.in mandi prices resource (no live API)](https://data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi)
- [Reading Sentinel-2 from Planetary Computer STAC](https://stacspec.org/en/tutorials/reading-stac-planetary-computer/)
- Rubric, rules and submission template: the Forge brief shared by the team
