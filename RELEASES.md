# RE_OS — Releases

## v2.0.0 — V2 Intelligence OS (2026-06-13)

Sprint 94 complete. Full land-stage intelligence pipeline operational.

**What shipped:**
- **Kaveri deed ingestion** — Form 17 EC parser, registered transaction scout, PSF spread from deed records
- **Leading demand indicators** — GCC hiring signals, DC conversion tracking, tender pipeline
- **Prediction ledger** — forecast tracking with calibration verdict (accuracy log for all PSF calls)
- **Off-site backup** — rclone push to remote, pg_restore verification
- **Parcel graph** — assembly detection, contiguous parcel scoring
- **Land supply intelligence** — Gazette LA notifications, Bhoomi ownership linkage

**Gates:** GATE-51 through GATE-94 (90 gates total)  
**Tests:** 2,043 unit tests passing  
**Alembic head:** `0060_dc_conversions`  
**Status:** GATE-91/92/93/94 🟡 conditional (live deed data pending)

---

## v1.0.0 — Launch Gate (2026-06-11)

Sprint 87 complete. System declared production-ready (GATE-87 LAUNCH GATE ✅).

**What shipped:**
- Full 3-stage pipeline: Data Crew → Organizer → Intel Crew
- Board Room v2 — 5 dept heads (BD, Finance, Engineering, Ops, Legal), concurrent evaluation
- PSF Forecaster — LightGBM-backed weekly price prediction
- Memory Explorer panel — agent memory read/write/decay/confidence tracking
- 33 scheduled jobs (APScheduler) — nightly RERA refresh, digests, PSF forecast, backups
- Discord alerts — Board Room digest, scraper health, backup staleness
- Operational Excellence — Alembic weekly check, Redis fallback CI, data floor alerts
- V2 readiness declaration endpoint (`/api/ops/v2-readiness`)

**Gates:** GATE-1 through GATE-87  
**Tests:** 1,824+ unit tests  
**Stack:** 7 Docker containers (PostgreSQL + PostGIS, Ollama, Redis, FastAPI, Scheduler, Prometheus, Grafana)

---

## v0.5.0 — HF Intelligence (2026-06-06)

Sprints 32–36 complete. Local AI inference stack live.

**What shipped:**
- BGE-M3 embeddings via Ollama (GPU inference confirmed — RTX 3050 CUDA 12.5)
- Semantic deduplication — e5-small-v2 + cross-encoder reranker
- Legal PDF QA — roberta-base-squad2 via LegalDocQATool
- FinBERT-tone directional sentiment on news articles
- QLoRA Qwen2.5-3B RERA extractor fine-tuned + deployed via Ollama

**Gates:** GATE-58, GATE-59, GATE-60

---

## v0.3.0 — V2 Intelligence Engine (2026-06-05)

Sprints 53–56 complete. V1 completion criteria met.

**What shipped:**
- V2 Unified Ingest Engine — 10+ plugins (RERA, Kaveri, IGR, news, listings)
- Opportunity Engine — scores ≥5 opportunities per market
- `/api/evaluate` — Board Room + Deal Memo + Investor Brief in one call
- Telegram → `/api/evaluate` → compact verdict pipeline
- Full end-to-end pipeline with feedback loop

**Gates:** GATE-45 through GATE-56 (all V1 completion criteria)

---

## v0.2.0 — Full Department Stack (2026-06-01)

Sprints 1–31 complete. All 6 departments operational.

**What shipped:**
- Legal Dept — RERAComplianceChecker, ZoneRiskChecker, EncumbranceChecker
- Finance Dept — IRR model, FeasibilityAnalystTool, automated Board Room IRR
- Engineering Dept — FSI calculator, Architect agent, Renderer agent, Green Coverage
- Phase 8.5 Intelligence — ChromaDB semantic search, FinBERT sentiment, APScheduler jobs
- Discord alerts live (GATE-14)
- Agent memory — read/write/decay/confidence, weekly decay cron

**Gates:** GATE-10 through GATE-17

---

## v0.1.0 — Seed System (2026-05-30)

Phase 1–2 complete. Dashboard live.

**What shipped:**
- 6 data scouts: RERA Karnataka, RERA Detail, Portal, Developer, News, Kaveri
- 3-stage pipeline: Data Crew → Python Organizer → Intel Crew
- FastAPI dashboard (port 8050) — 6 panels, health endpoints
- Board Room v1 — 5 dept heads (CrewAI-based)
- PostGIS database — 16 tables, 4 analytics views
- Playwright AJAX intercept for RERA JavaScript portal

**Markets:** Yelahanka, Devanahalli, Hebbal  
**Gates:** GATE-2, GATE-4, GATE-7, GATE-8, GATE-9
