---
title: KhetKavach API
emoji: 🌾
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Farm-level climate risk agent for India (backend API)
---

# KhetKavach backend

FastAPI + LangGraph agent that streams a farm's climate-risk analysis as Server-Sent Events.
Health check: `GET /health`. Main endpoint: `GET /api/analyze?lat=..&lon=..&crop=wheat`.

Set these as Space **secrets/variables** (Settings → Variables and secrets): `GEMINI_API_KEY`, `GEMINI_MODEL`,
`SARVAM_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `NOMINATIM_USER_AGENT`, `ALLOWED_ORIGINS`, `DEMO_CONTROLS`.

See the main repository README for the architecture, data provenance and risk method.
