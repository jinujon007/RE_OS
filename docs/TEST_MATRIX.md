# RE_OS — Test Matrix
**Last updated: 2026-07-03 | Gates: 172 ✅ (169/171/172 pre-built) | Test files: 325+ | Next Sprints: 163-168 (coverage audit), 170 (market expansion), 173-176 (BD intelligence)**

Master reference for testing every aspect of RE_OS. Use this to find the right test, understand what it covers, and know if Docker is required.

---

## 1. How to Run Tests

```bash
# Unit tests — no Docker required, pure Python:
pytest tests/ -m "not integration" -v

# Gate tests only — fastest signal, 5 assertions per gate:
pytest tests/test_gate*.py -v

# Coverage audit (Sprint 163) — no Docker:
pytest \
  tests/test_api_coverage.py \
  tests/test_scheduler_coverage.py \
  tests/test_mcp_coverage.py \
  tests/test_utils_coverage.py \
  tests/test_migration_chain.py \
  -v

# Integration tests — Docker stack must be up:
docker compose up -d
docker compose exec agents pytest tests/integration/ -m integration -v

# Single integration test:
docker compose exec agents pytest tests/integration/test_api_live.py -m integration -v

# Single gate:
docker compose exec agents pytest tests/test_gate155.py -v

# With coverage report:
docker compose exec agents pytest tests/ -m "not integration" \
  --cov=utils --cov=dashboard --cov=crews --cov=config \
  --cov-report=term-missing
```

### Pytest Markers

| Marker | Description | Auto-skip? | Used by |
|--------|-------------|-----------|---------|
| `unit` | Pure Python, no DB, no network | Never | All gate tests |
| `integration` | Requires live PostgreSQL / Docker stack | Yes — skips when DB port 5432 unreachable | `tests/integration/` + `test_board_room_smoke.py` |
| `slow` | Runtime > 10s | Never | Marketplace pipeline (300s), Board Room (180s) |
| `test_id(ID)` | Traceability to GATE criterion (e.g. `G164-A2`) | Never | All Gate-164 integration tests |

### Important Notes

- All `docker compose exec agents pytest ...` commands assume the agents container has the test environment. For local runs without Docker stack, unit tests use the `tests/conftest.py` mocks.
- Integration tests skip automatically when the Docker stack is unreachable (socket check on port 5432). No manual `@pytest.mark.skipif` needed.
- The `slow` marker identifies tests that may take >10s. Run separately with `pytest -m slow` if you want to isolate them.

---

## 2. Unit Test Inventory

All 321 gate test files grouped by domain. Each component's key assertions cover both happy path and failure modes (DB errors, missing data, edge cases).

### Intelligence Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| ParcelGraph (shared-buyer aggregation) | `test_gate155.py` | 155 | `build()` returns nodes+edges; null-date floor weight; DB failure returns empty; 500-node trim | `pytest tests/test_gate155.py -v` |
| STRROverlay (transit proximity) | `test_gate156.py` | 156 | `stations_near()` returns stations; transit signal string; no errors on DB failure | `pytest tests/test_gate156.py -v` |
| IntelligenceCalibrator (MAPE tracking) | `test_gate157.py` | 157 | `run_calibration_check()` 6 keys; DB failure returns None values; overall_health logic | `pytest tests/test_gate157.py -v` |
| DigestValidator (quality gate) | `test_gate158.py` | 158 | `validate_digest()` PASS/WARN/FAIL; market_coverage=False → FAIL; partial DB failure → WARN | `pytest tests/test_gate158.py -v` |
| AssemblyDetector (DBSCAN + ST-DBSCAN) | `test_assembly_detector.py` | 154+ | `detect_clusters()` returns list; DB failure returns empty; min_points filter; adjacency merge | `pytest tests/test_assembly_detector.py -v` |
| CorridorScorer (composite + backtest) | `test_gate152.py` | 152 | `score_all()` returns dict by market; corridor composite scores; DB failure returns empty | `pytest tests/test_gate152.py -v` |
| DealScorer (GO/NO-GO synthesis) | `test_gate161.py` | 161 | `score_deal()` 5 signals; all-fallback confidence <1.0; input validation raises ValueError; verdict thresholds | `pytest tests/test_gate161.py -v` |
| InvestorBriefGenerator | `test_gate148.py` | 148 | brief contains market name, PSF trend, STRR signal, assembly count; DB failure returns fallback text | `pytest tests/test_gate148.py -v` |
| Parcel Hardening (geometry centroid) | `test_gate162.py` | 162 | DB centroid used when available; fallback to hardcoded coords on DB error; station TTL reload cap; parcel-graph stats endpoint | `pytest tests/test_gate162.py -v` |

### Visualization Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| ParcelGraph Cytoscape (JS vis) | `test_gate159.py` | 159 | Cytoscape HTML returned; nodes/edges from parcel_graph; no JS errors; empty graph renders placeholder | `pytest tests/test_gate159.py -v` |
| Multi-Market Investor Digest | `test_gate160.py` | 160 | digest_text contains all 3 markets; bullet points per section; no hallucination markers | `pytest tests/test_gate160.py -v` |

### Data Pipeline Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| RERA Scraper | `test_rera_karnataka.py` | 45 | fetches project list; parses rera_number; handles pagination | `pytest tests/test_rera_karnataka.py -v` |
| Portal Scout (scraperling) | `test_portal_scout.py` | 134+ | scout discovers portal pages; fallback chain works; timeout handling | `pytest tests/test_portal_scout.py -v` |
| Kaveri Scraper (deed portal) | `test_kaveri_scraper.py` | 44+ | fetches deed data; parses Form17 fields; handles captcha fallback | `pytest tests/test_kaveri_scraper.py -v` |
| Form17 Parser (PDF extraction) | `test_form17_parser.py` | 95 | parses PDF; extracts seller/buyer/PSF; handles corrupted PDFs gracefully; encoding fallback | `pytest tests/test_form17_parser.py -v` |
| Deed Progress / Priority Villages | `test_gate153.py` | 153 | `get_priority_villages()` returns ranked list; `kaveri_url_hint` format correct; DB failure returns [] | `pytest tests/test_gate153.py -v` |
| Deed Inbox Validation | `test_gate169.py` | 169 | `validate_inbox_pdfs()` detects corrupted/empty/non-PDF files; daily status telegram | `pytest tests/test_gate169.py -v` |

### Board Room Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| 5 Dept Heads (session orchestration) | `test_board_room.py` | 87+ | session creation; 5 agent responses; timeout guard; error handling | `pytest tests/test_board_room.py -v` |
| GO/NO-GO Formatter | `test_board_room_formatter.py` | 129 | verdict extraction; confidence score; recommendation text; negation handling | `pytest tests/test_board_room_formatter.py -v` |
| STRR Context injection | `test_gate156.py (A4)` | 156 | STRR signal injected into board room context | `pytest tests/test_gate156.py -v` |

### Scheduler Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| Deed Jobs | `test_gate145.py`, `test_scheduler_coverage.py` | 145, 163 | jobs importable; `__all__` populated; `register_jobs()` callable; combined count ≥20 | `pytest tests/test_gate145.py tests/test_scheduler_coverage.py -v` |
| Forecast Jobs | `test_gate147.py`, `test_scheduler_coverage.py` | 147, 163 | weekly digest job importable; market list coverage | `pytest tests/test_gate147.py tests/test_scheduler_coverage.py -v` |
| Maintenance Jobs | `test_gate150.py`, `test_scheduler_coverage.py` | 150, 163 | backup/health/DLQ jobs importable; schedule validation | `pytest tests/test_gate150.py tests/test_scheduler_coverage.py -v` |
| Intel Jobs | `test_scheduler_coverage.py` (Sprint 165) | 165 | VEL update, intel digest jobs importable; `__all__` present | `pytest tests/test_scheduler_coverage.py -v` |
| Kaveri Jobs | `test_scheduler_coverage.py` (Sprint 165) | 165 | deed daily status importable; `__all__` present | `pytest tests/test_scheduler_coverage.py -v` |
| RERA Jobs | `test_scheduler_coverage.py` (Sprint 165) | 165 | scraper jobs importable; `__all__` present | `pytest tests/test_scheduler_coverage.py -v` |
| Digest Jobs | `test_scheduler_coverage.py` (Sprint 165) | 165 | digest jobs importable; `__all__` present | `pytest tests/test_scheduler_coverage.py -v` |

### MCP Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| Tool Registry (5+ tools) | `test_mcp_coverage.py` | 163 | all tools registered; each has name/description/inputSchema; no duplicates | `pytest tests/test_mcp_coverage.py -v` |

### Database Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| Schema (core tables) | `test_schema_v2.py` | 90+ | core tables exist; FK constraints valid; indexes present | `pytest tests/test_schema_v2.py -v` |
| Migrations (77 revisions) | `test_migration_chain.py` | 163 | all migrations importable; chain forms DAG; single head (0077_deal_score_log) | `pytest tests/test_migration_chain.py -v` |

### API Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| Route Registration (13 routes) | `test_api_coverage.py` | 163 | routes registered; OPTIONS preflight; `/api/health` + `/api/v1/ops/kill-criteria` present | `pytest tests/test_api_coverage.py -v` |
| RBAC / Auth (3-tier) | `test_api_rbac.py` | 161+ | read/write/admin key separation; no-auth mode (ALLOW_EMPTY); key rotation (PREV) | `pytest tests/test_api_rbac.py -v` |

### Notifications Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| Discord Notifier | `test_discord_notifier.py` | 130+ | `send_ops_alert()` sends message; handles API failure gracefully | `pytest tests/test_discord_notifier.py -v` |
| Telegram Notifier | `test_telegram_e2e.py` | 142 | `send_message()` sends message; markdown formatting preserved | `pytest tests/test_telegram_e2e.py -v` |

### Ops Domain

| Component | Test File(s) | Gate(s) | Key Assertions | Run Command |
|-----------|-------------|---------|---------------|-------------|
| Kill Criteria (deed throughput) | `test_gate149.py` | 149 | deed throughput projection; decision journal count; status logic | `pytest tests/test_gate149.py -v` |
| V2 Readiness | `test_v2_readiness.py` | 90 | readiness checks; conditional gate status; version reporting | `pytest tests/test_v2_readiness.py -v` |
| Calibration (MAPE health) | `test_gate157.py` | 157 | calibrator endpoint returns 6 keys; health aggregator works | `pytest tests/test_gate157.py -v` |
| Digest Quality (per-market) | `test_gate158.py` | 158 | quality check endpoint; per-market verdicts; any_failures flag | `pytest tests/test_gate158.py -v` |

---

## 3. Integration Test Suite

Docker stack required: `docker compose up -d`. Run via `docker compose exec agents pytest tests/integration/ -m integration -v`.

| Test File | What It Tests | Expected Output | Setup Requirements | Duration |
|-----------|--------------|-----------------|-------------------|----------|
| `test_pipeline_smoke.py` | Full `market_intel_crew.py --market Yelahanka` run via subprocess | Exit code 0; ≥1 `agent_runs` row created within 10 min window; `micro_markets` row for Yelahanka exists with name + slug | DB + agents containers | ~300s |
| `test_api_live.py` | 20 live API endpoints against `http://localhost:8050` | All return non-500; health returns `{"status":"healthy"}`; each endpoint has expected structure keys; intel cards returns ≥1 card | agents container | ~30s |
| `test_deal_score_live.py` | `score_deal()` for Yelahanka/Devanahalli/Hebbal (parametrized) + InvalidMarket fallback | All return valid dicts; `overall_score∈[0,1]`; `verdict∈{GO,CAUTIOUS,NO-GO}`; `confidence>0`; 5 signal keys present; `strr_signal` valid; `market` + `generated_at` fields present | DB + agents containers | ~10s |
| `test_board_room_enhanced.py` | Board room session via `run_board_session()` + `get_board_session()` polling | Session row created; async completion with 5 dept heads in transcript; GO/NO-GO verdict; STRR signal; `decision_flag` present; `decision_journal` entry | DB + agents containers | ~150s (LLM-dependent) |
| `test_db_organizer_pipeline.py` | RERA project insert/update/skip/failed tracking | Insert new record; update existing; skip invalid; totals correct; developer grade assigned | DB container only | ~10s |

### Test Ordering and Isolation

- Each test file has its own cleanup via `conftest.py` fixtures (`autouse` scope).
- `test_pipeline_smoke.py` and `test_board_room_enhanced.py` are marked `@pytest.mark.slow` — they may take several minutes.
- Integration tests are independent of each other and can run in any order.
- Stale `agent_runs` rows for `test_%` markets are cleaned at module setup to prevent cross-test pollution.

---

## 4. Manual Verification Checklist

These J-steps are the acceptance criteria for conditional gates. Run in order.

| Step | Command | Expected Output | Closes |
|------|---------|-----------------|--------|
| J-20 | `docker compose up -d` | All containers healthy (agents, db, scheduler, redis, ollama) — 7 with observability stack | Precondition |
| J-21 | Drop PDFs in `data/inbox/` + `docker compose exec agents python scripts/process_deed_inbox.py` | ≥1 row in `registered_transactions`; invalid PDFs flagged in `dead_letter_queue` | GATE-91, GATE-169 |
| J-22 | `docker compose exec agents python scripts/check_conditional_gates.py` | All 🟡 show as ✅ if data present | GATE-91/92/93/94/95 |
| J-23 | `docker compose exec agents python crews/market_intel_crew.py --market Yelahanka` | Intel report in `outputs/`; `agent_runs` row created within 10 min | GATE-93/94 |
| J-24 | `docker compose exec agents python crews/board_room.py` | Board session row in `board_sessions` table; 5 dept head responses; GO/NO-GO verdict | GATE-95 |
| J-25 | `curl -X POST http://localhost:8050/api/ops/v2-declare -H "X-API-Key: $DASHBOARD_API_KEY"` | `{"declared": true, "timestamp": "..."}` | GATE-149 |
| J-26 | `docker compose exec agents pytest tests/integration/ -m integration -v` | All 5 integration tests pass (or skip gracefully if LLM unavailable) | GATE-164 |

### Post-Deployment Validation

After any major deployment, run the full integration suite and gate tests:
```bash
docker compose exec agents pytest tests/integration/ -m integration -v
docker compose exec agents pytest tests/test_gate*.py -v
```

---

## 5. Gate Status Dashboard

All 162 gates with current status.

### Gates 1-144 (Legacy)

All ✅ DONE. These cover the foundational RE_OS architecture: data pipelines (scrapers, parsers, organizers), intelligence modules (market briefs, demand signals, land intelligence, financial intelligence), portal infrastructure (CrewAI agents, MCP tools, scheduler jobs), ops dashboard (routes, metrics, audit), and the first 144 sprint gates. See `VISION.md` for full historical log.

### Gates 145-172 (Active + Planned)

| Gate | Sprint | Focus | Status |
|------|--------|-------|--------|
| 145 | 145 | Deed Reminder Pipeline (scheduler + Telegram) | ✅ DONE |
| 146 | 146 | Decision Journal Intelligence (board auto-create) | ✅ DONE |
| 147 | 147 | Multi-Market Weekly Digest (3 markets) | ✅ DONE |
| 148 | 148 | Investor Brief + Obsidian Export | ✅ DONE |
| 149 | 149 | Kill Criteria Endpoint + Scraperling Portal Scout | ✅ DONE |
| 150 | 150 | Alembic Health + DLQ Drain + Backup | ✅ DONE |
| 151 | 151 | Form17 Deep Extraction + Corridor Backtest | ✅ DONE |
| 152 | 152 | Corridor Scorer (composite + radius + backtest) | ✅ DONE |
| 153 | 153 | Deed Download Priority + Kaveri Reminder | ✅ DONE |
| 154 | 154 | Assembly Detector (DBSCAN + ST-DBSCAN + adjacency) | ✅ DONE |
| 155 | 155 | Parcel Graph (shared-buyer + weighted edges + Cytoscape) | ✅ DONE |
| 156 | 156 | STRR Overlay (Namma Metro + K-RIDE + Board Room integration) | ✅ DONE |
| 157 | 157 | Intelligence Calibrator (MAPE + confidence + health) | ✅ DONE |
| 158 | 158 | Digest Validator (quality gate + Discord + endpoint) | ✅ DONE |
| 159 | 159 | Parcel Graph Visualization (Cytoscape.js + materialization + hotspot) | ✅ DONE |
| 160 | 160 | Multi-Market Investor Digest (Obsidian + Telegram + STRR config) | ✅ DONE |
| 161 | 161 | Live Deal Scoring (DealScorer + endpoint + MCP tool + deal_score_log) | ✅ DONE |
| 162 | 162 | Audit Residuals (geometry centroid, TTL reload, stats endpoint, chain) | ✅ DONE |
| 163 | 163 | System Coverage Audit (routes, scheduler, MCP, utils, migrations) | 🔵 PLANNED |
| 164 | 164 | Integration Smoke Suite (pipeline, API, deal score, board room) | ✅ DONE |
| 165 | 165 | Scheduler Full Coverage (all 7 modules, `__all__` for 4 missing, 30+ jobs) | 🔵 PLANNED |
| 166 | 166 | News Sentiment Quality + Threshold Config | 🔵 PLANNED |
| 167 | 167 | 90 Utils + 19 Scraper Import Coverage | 🔵 PLANNED |
| 168 | 168 | SLO + Handover Doc + Ops Dashboard | 🔵 PLANNED |
| 169 | 169 | Deed PDF Validation + Daily Status | 🔵 PLANNED |
| 170 | 170 | Thanisandra + Bagalur Market Expansion | 🔵 PLANNED |
| 171 | 171 | VEL Weekly Intelligence (Hebbal + Yelahanka PSF) | 🔵 PLANNED |
| 172 | 172 | FinBERT Sentiment (financial news feed) | 🔵 PLANNED |

---

## 6. Coverage Gaps

Components where unit tests exist but integration (live-stack) validation is incomplete.

| Component | Unit Test(s) | Integration Coverage | Risk Level | Notes |
|-----------|-------------|---------------------|-----------|-------|
| ParcelGraph | `test_gate155.py` | None | Low | Pure computation, no I/O |
| STRROverlay | `test_gate156.py` | None | Medium | Station CSV file path resolution varies by container |
| IntelligenceCalibrator | `test_gate157.py` | None | Low | Pure computation, no I/O |
| DigestValidator | `test_gate158.py` | None | Low | Query-only, no external deps |
| AssemblyDetector | `test_assembly_detector.py` | None | Low | DBSCAN computation only |
| CorridorScorer | `test_gate152.py` | None | Low | Pure computation |
| DealScorer | `test_gate161.py` | ✅ `test_deal_score_live.py` (Sprint 164) | — | 3-market parametrized + fallback |
| Board Room | `test_board_room.py`, `test_board_room_formatter.py` | ✅ `test_board_room_enhanced.py` (Sprint 164) | — | Async polling with transcript validation |
| MCP Tools | `test_mcp_coverage.py` | None | Medium | Tool registration vs. actual runtime in CrewAI |
| Full Pipeline | `test_gate_*.py` | ✅ `test_pipeline_smoke.py` (Sprint 164) | — | Subprocess run + DB side-effect assertions |
| Live API | `test_api_coverage.py` | ✅ `test_api_live.py` (Sprint 164) | — | 20 endpoints, structured response validation |
| Kaveri Scraper | `test_kaveri_scraper.py` | None | **High** | Portal structure changes break parsing |
| RERA Scraper | `test_rera_karnataka.py` | None | **High** | Portal structure changes break parsing |
| Telegram Notifier | `test_telegram_e2e.py` | None | Medium | Bot token + network required |
| Discord Notifier | `test_discord_notifier.py` | None | Medium | Webhook URL + network required |
| Form17 Parser | `test_form17_parser.py` | None | **High** | Kaveri PDF format changes break extraction |

### Gap Closure Priority

1. **High** (external dependencies): Kaveri scraper, RERA scraper, Form17 parser — portal changes are outside our control. Weekly integration runs recommended.
2. **Medium** (env-dependent): MCP tools, Telegram, Discord, STRROverlay — need network + API keys in CI.
3. **Low** (computation-only): ParcelGraph, Calibrator, CorridorScorer — algorithmic correctness verified by unit tests.

---

## 7. Regression Guards

These tests catch the most common failure modes. Run before every commit or deploy.

```bash
# API route registration (catches missing endpoints):
pytest tests/test_api_coverage.py -v

# Migration chain integrity (catches orphan/broken migrations):
pytest tests/test_migration_chain.py -v

# Scheduler job registration (catches unregistered jobs):
pytest tests/test_scheduler_coverage.py -v

# DealScorer (catches scoring logic regressions):
pytest tests/test_gate161.py -v

# Board Room formatter (catches verdict/recommendation regressions):
pytest tests/test_board_room_formatter.py -v
```

### Post-Deployment Smoke (Sprint 164)

Run the full integration suite after any major change:

```bash
docker compose exec agents pytest tests/integration/ -m integration -v
```

This validates:
- Pipeline orchestration works end-to-end (`test_pipeline_smoke.py`)
- All 20 API endpoints respond with expected structure (`test_api_live.py`)
- Deal scoring generates valid results for all target markets (`test_deal_score_live.py`)
- Board Room session lifecycle completes end-to-end (`test_board_room_enhanced.py`)
- DB organizer pipeline correctly inserts/updates/fails (`test_db_organizer_pipeline.py`)
