# RE_OS — Test Matrix
**Last updated: 2026-06-29 | Gates: 162 ✅ | Test files: 321 | Next Sprint: 163 (coverage audit)**

Master reference for testing every aspect of RE_OS. Use this to find the right test, understand what it covers, and know if Docker is required.

---

## How to Run Tests

```bash
# All unit tests (no Docker required):
docker compose exec agents pytest tests/ -m "not integration" -v

# Gate tests only (fastest signal):
docker compose exec agents pytest tests/test_gate*.py -v

# Sprint 163 coverage audit (no Docker):
docker compose exec agents pytest tests/test_api_coverage.py tests/test_scheduler_coverage.py tests/test_mcp_coverage.py tests/test_utils_coverage.py tests/test_migration_chain.py -v

# Integration tests (Docker required — stack must be up):
docker compose up -d
docker compose exec agents pytest tests/integration/ -m integration -v

# Single gate:
docker compose exec agents pytest tests/test_gate155.py -v

# Run with coverage report:
docker compose exec agents pytest tests/ -m "not integration" --cov=utils --cov=dashboard --cov=config --cov-report=term-missing

# Quick smoke (5 regression guards — run after any major change):
docker compose exec agents pytest tests/test_api_coverage.py tests/test_migration_chain.py tests/test_scheduler_coverage.py tests/test_gate161.py tests/test_board_room_formatter.py -v
```

---

## Unit Test Inventory (No Docker Required)

### Intelligence Layer

| Component | Test File(s) | Gate | Key Assertions |
|-----------|-------------|------|---------------|
| ParcelGraph (shared-buyer aggregation) | `test_gate155.py` | 155 | build() returns nodes+edges; null-date floor weight; DB failure returns empty; 500-node trim |
| STRROverlay (transit proximity) | `test_gate156.py` | 156 | stations_near() returns sorted list; transit_signal() STRONG/MODERATE/WEAK; empty stations → WEAK; unknown market → [] |
| IntelligenceCalibrator (MAPE tracking) | `test_gate157.py` | 157 | run_calibration_check() 6 keys; DB failure returns None values not raise; overall_health logic |
| DigestValidator (quality gate) | `test_gate158.py` | 158 | validate_digest() PASS/WARN/FAIL; market_coverage=False → FAIL; partial DB failure → WARN |
| AssemblyDetector (parcel assembly) | `test_assembly_detector.py`, `test_gate146.py` | 140, 146 | detect_clusters() confidence scores; detect_time_series() 6-month windows; ALERT tier thresholds |
| CorridorScorer (growth corridor) | `test_gate152.py`, `test_gate95.py` | 95, 152 | score_all(); backtest() MAPE; corridor_backtest_results table |
| DealScorer (GO/NO-GO synthesis) | `test_gate161.py` | 161 | score_deal() 5 signals; all-fallback confidence <1.0; input validation raises ValueError; verdict thresholds |
| InvestorBriefGenerator | `test_gate148.py` | 148 | generate() 6-section brief; multi-market compare; VEL analysis |
| AssemblyDetector Time-Series | `test_gate151.py` | 151 | detect_time_series() rolling windows; assembly-timeline endpoint |
| Parcel Graph Visualisation | `test_gate159.py` | 159 | parcel_graph.html exists + cytoscape include; hotspot-alert endpoint; materialization job importable |
| Multi-Market Investor Digest | `test_gate160.py` | 160 | run_weekly_investor_digest importable; Obsidian write called; STRR_STRONG_KM config constant |
| Parcel Hardening (audit residuals) | `test_gate162.py` | 162 | _db_centroid fallback; TTL reload; parcel stats endpoint; migration chain 0074→0077 |
| PSF Forecaster | `test_gate85.py`, `test_appreciation_model.py` | 85 | market_forecasts table; PSF prediction |
| Prediction Ledger | `test_gate139.py`, `test_gate147.py` | 139, 147 | prediction_tracker.compute_mape(); 4wk model_version; MAPE panel |
| Corridor PostGIS | `test_gate100.py` | 100 | PostGIS corridor geometry queries |
| IRR Model | `test_gate_irr.py`, `test_gate13.py` | 13 | calc_irr(); ScenarioComparator; GDV reconciliation |

### Data Pipeline

| Component | Test File(s) | Gate | Key Assertions |
|-----------|-------------|------|---------------|
| RERA Karnatala Scraper | `test_rera_karnataka.py` | 45 | Playwright AJAX intercept; hardcoded fallback; checkpoint save |
| Portal Scout (99acres/MagicBricks) | `test_portal_scout.py` | 45 | 7 portals; listing extraction; dedup |
| Developer Scout (Brigade/Prestige) | `test_developer_scout.py` | 45 | 8 developer sites; project page parsing |
| News Scout (Google News + ET Realty) | `test_news_scout.py` | 45 | Google News; ET Realty; fallback |
| Kaveri Scraper (guidance values) | `test_kaveri_scraper.py` | 78 | guidance value extraction; registration data |
| KaveriForm17Plugin (Form 17) | `test_form17_parser.py`, `test_gate95.py` | 95 | form17 PDF parsing; village extraction; survey numbers |
| RERA Circuit Breaker | `test_scraper_circuit_breaker.py` | 128 | breaker opens after N failures; reset after timeout |
| Deed Progress | `test_gate153.py`, `test_deed_progress.py` | 145, 153 | get_priority_villages(); compute_throughput_projection(); download-guide endpoint |
| Bhoomi RTC Parser | `test_bhoomi_rtc_parser.py` | 99 | Form 15 extraction; EC parsing |

### Database & Migrations

| Component | Test File(s) | Gate | Key Assertions |
|-----------|-------------|------|---------------|
| Schema v2 | `test_schema_v2.py` | multiple | 16 tables + 4 views exist; index presence |
| Alembic migration chain | `test_migration_chain.py` (Sprint 163) | 163 | 0001→0077 valid DAG; no cycles; single head |
| Alembic health check | `test_alembic_health.py` | 88, 150 | run_alembic_health_check() importable; head detection |
| Alembic upgrade | `test_alembic_upgrade.py` | multiple | upgrade head succeeds |
| DB integrity | `test_gate110.py` | 110 | referential integrity; constraint violations handled |
| DB performance | `test_gate111.py` | 111 | index usage; query plan |
| Backup | `test_backup.py` | 112 | backup job runs; output file created |

### Board Room

| Component | Test File(s) | Gate | Key Assertions |
|-----------|-------------|------|---------------|
| 5 Dept Heads | `test_board_room.py`, `test_gate10.py` | 10, 87 | BD/Finance/Eng/Ops/Legal all respond; concurrent execution |
| GO/NO-GO Formatter | `test_board_room_formatter.py` | 129 | formatter output structure; verdict present |
| Board Room STRR context | `test_gate156.py` (A4) | 156 | BD Head receives STRR signal in context |
| Board Room Corridor context | `test_gate152.py` (A4) | 152 | Finance Head receives corridor MAPE |
| Board Room Assembly context | `test_assembly_board_context.py` | 146 | Ops Head receives assembly signal count |
| Board Room Timing | `test_board_timing.py` | 87 | full session completes <60s |
| Board Room Forecast | `test_board_room_forecast.py` | 85 | PSF forecast injected into CEO context |
| Board Room Smoke | `test_board_room_smoke.py` | 87 | 5 dept heads respond; board_sessions row created |
| Decision Journal Auto-Create | `test_gate137.py` | 137 | GO/NO-GO auto-creates journal entry |

### Scheduler Jobs

| Component | Test File(s) | Gate | Key Assertions |
|-----------|-------------|------|---------------|
| Kill criteria report (Mon 10:00 IST) | `test_gate150.py` | 150 | run_weekly_kill_criteria_report importable; Telegram + Discord called |
| Alembic health check (Mon 06:30 UTC) | `test_gate150.py` | 150 | run_alembic_health_check importable |
| DLQ drain check (Mon 09:30 UTC) | `test_gate150.py` | 150 | run_dlq_drain_check importable; Discord on >10 stale |
| Weekly calibration (Fri 23:00 UTC) | `test_gate157.py` | 157 | run_weekly_calibration importable; MAPE>25% Discord alert |
| Digest quality check (Sat 08:00 UTC) | `test_gate158.py` | 158 | run_digest_quality_check importable; Discord on FAIL |
| Weekly investor digest (Mon 01:30 UTC) | `test_gate160.py` | 160 | run_weekly_investor_digest importable; Obsidian + Telegram |
| Parcel materialization (Sun 01:00 UTC) | `test_gate159.py` | 159 | run_parcel_graph_materialize importable |
| RERA scrape (2AM UTC daily) | `test_stage1_crew.py` | multiple | scrape_rera checkpoint saved |
| Download reminder (Mon 09:00 IST) | `test_gate145.py` | 145 | run_kaveri_download_reminder; priority villages in message |
| Assembly detection (Mon 07:00 UTC) | `test_gate140.py` | 140 | run_assembly_detection importable |
| Forecast job (Mon 06:00 UTC) | `test_gate139.py` | 139 | run_weekly_forecast importable |
| All jobs coverage | `test_scheduler_coverage.py` (Sprint 163) | 163 | ≥20 jobs combined; all registered; none start as running |

### MCP Tools

| Tool | Test File(s) | Gate | Key Assertions |
|------|-------------|------|---------------|
| investor_brief | `test_gate143.py` | 143 | tool in TOOLS list; schema has required params |
| vel_competitive_report | `test_gate154.py` | 154 | tool registered; _CACHED_TOOL_NAMES |
| deal_score | `test_gate161.py` | 161 | tool registered; inputSchema has market/land_cost_cr/area_acres |
| All tools coverage | `test_mcp_coverage.py` (Sprint 163) | 163 | ≥5 tools; no duplicates; all have inputSchema |

### API Endpoints

| Endpoint | Test File(s) | Gate | Docker? |
|----------|-------------|------|---------|
| GET /api/health | `test_gate2.py` | 2 | No |
| GET /api/v1/ops/kill-criteria | `test_gate149.py` | 149 | No |
| GET /api/v1/ops/handover-doc | `test_gate149.py` | 149 | No |
| GET /api/v1/ops/v2-readiness | `test_v2_readiness.py` | 90 | No |
| GET /api/v1/ops/calibration | `test_gate157.py` | 157 | No |
| GET /api/v1/ops/digest-quality | `test_gate158.py` | 158 | No |
| GET /api/v1/intel/deal-score | `test_gate161.py` | 161 | No |
| GET /api/v1/intel/deal-score/history | `test_gate161.py` | 161 | No |
| GET /api/v1/intel/parcel-graph | `test_gate155.py` | 155 | No |
| GET /api/v1/intel/parcel-graph/summary | `test_gate155.py` | 155 | No |
| GET /api/v1/intel/parcel-graph/stats | `test_gate162.py` | 162 | No |
| GET /api/v1/intel/parcel-graph/hotspot-alert | `test_gate159.py` | 159 | No |
| GET /api/v1/intel/strr-overlay | `test_gate156.py` | 156 | No |
| GET /api/v1/intel/investor/weekly-digest | `test_gate160.py` | 160 | No |
| GET /api/v1/intel/assembly-alerts | `test_gate146.py` | 146 | No |
| GET /api/v1/intel/assembly-timeline | `test_gate151.py` | 151 | No |
| GET /api/v1/intel/corridors/backtest-accuracy | `test_gate152.py` | 152 | No |
| GET /api/v1/deeds/download-guide | `test_gate153.py` | 153 | No |
| GET /api/v1/intel/vel/competitive-report | `test_gate154.py` | 154 | No |
| GET /api/v1/intel/vel/pricing-sensitivity | `test_gate154.py` | 154 | No |
| POST /api/v1/intel/vel/export-obsidian | `test_gate154.py` | 154 | No |
| GET /api/v1/intel/digest/latest | `test_gate158.py` | 158 | No |
| GET /api/v1/intel/forecast-accuracy | `test_gate147.py` | 147 | No |
| GET /api/v1/ops/ledger/full | `test_gate147.py` | 147 | No |
| GET /api/v1/intel/investor/compare | `test_gate148.py` | 148 | No |
| GET /parcel-graph (dashboard) | `test_gate159.py` | 159 | No |
| GET /api/agents | `test_gate2.py` | 2 | No |
| GET /api/board/sessions | `test_board_room_smoke.py` | 87 | No |
| GET /api/intel/cards | `test_gate46.py` | 46 | No |
| All routes registered | `test_api_coverage.py` (Sprint 163) | 163 | No |

### Notifications

| Component | Test File(s) | Gate | Key Assertions |
|-----------|-------------|------|---------------|
| Discord (5 formatters) | `test_discord_notifier.py` | 14 | send_ops_alert(); RERA alert; market brief formatter |
| Telegram | `test_telegram_e2e.py`, `test_telegram_webhook.py` | 142 | send_message(); Board Room delivery; assembly alert |

### Operations

| Component | Test File(s) | Gate | Key Assertions |
|-----------|-------------|------|---------------|
| Agent Memory | `test_write_memory.py` | Phase 4 | read/write/decay/confidence; weekly decay cron |
| ChromaDB / Embeddings | `test_chromadb_maintenance.py` | 8.5 | IntelEmbedder; semantic search returns results |
| FinBERT Sentiment | `test_sentiment.py`, `test_sentiment_tone.py` | 8.5, 35 | finbert-tone; directional sentiment; CI BERTScore |
| Legal PDF QA | `test_gate58.py` | 34, 58 | LegalDocQATool; roberta-base-squad2 |
| SLO Burn | `test_slo_burn_check.py`, `test_slo_endpoint.py` | 116, 120 | SLO budget; burn rate alert |
| API RBAC | `test_api_rbac.py` | 8 | X-API-Key auth; read-only paths exempt |
| Alert Suppressor | `test_alert_suppressor.py` | 88 | 168h cooldown; no duplicate Discord alerts |
| Audit Log | `test_audit_log.py` | multiple | agent_runs event recording |
| Secrets Baseline | `test_secrets_baseline.py` | 84 | no hardcoded secrets in codebase |

---

## Integration Tests (Docker Required)

**Prerequisites:** `docker compose up -d` → all 5 containers healthy.

```bash
# Verify stack health before running:
docker compose ps
curl http://localhost:8050/api/health
```

| Test File | Gate | What It Tests | Estimated Time |
|-----------|------|---------------|----------------|
| `tests/integration/test_pipeline_smoke.py` | 164 | Full scrape → organize → intel → agent_runs row | 3-5 min |
| `tests/integration/test_api_live.py` | 164 | 20 API endpoints against live DB | 30s |
| `tests/integration/test_deal_score_live.py` | 164 | score_deal() for all 3 markets with real PSF data | 15s |
| `tests/integration/test_board_room_enhanced.py` | 164 | 5 dept heads + GO/NO-GO + board_sessions row | 1-2 min |

**Note:** Integration tests require `DASHBOARD_API_KEY` from `.env` to be set. Auth header: `X-API-Key: {key}`.

---

## Manual Verification Checklist (Jinu J-Tasks)

Run these in order after `docker compose up -d` (J-20):

| Step | Command | Expected Output | Closes Gate |
|------|---------|-----------------|-------------|
| J-20 | `docker compose up -d` | 5 containers Up | Precondition |
| J-21 | Drop Form17 PDFs → `scripts/process_deed_inbox.py` | ≥1 row in `registered_transactions` | GATE-91 |
| J-22 | `scripts/check_conditional_gates.py` | GATE-91/92/93/94/95 show ✅ if data present | GATE-91-95 |
| J-23 | `docker compose exec agents python crews/market_intel_crew.py` | Intel report in `outputs/` folder | GATE-93/94 |
| J-24 | `docker compose exec agents python crews/board_room.py` | Board session saved to `board_sessions` | GATE-95 |
| J-25 | `curl -X POST http://localhost:8050/api/ops/v2-declare -H "X-API-Key: $KEY"` | `{"declared": true}` | GATE-149 |

---

## 5 Regression Guards — Run After Any Major Change

These 5 tests catch the most common failure modes. Run them before every commit.

```bash
docker compose exec agents pytest \
  tests/test_api_coverage.py \
  tests/test_migration_chain.py \
  tests/test_scheduler_coverage.py \
  tests/test_gate161.py \
  tests/test_board_room_formatter.py \
  -v
```

| Test | Catches |
|------|---------|
| `test_api_coverage.py` | Missing route registration after adding new endpoint |
| `test_migration_chain.py` | Broken Alembic chain after adding migration |
| `test_scheduler_coverage.py` | Scheduler job not in `__all__` or not registered |
| `test_gate161.py` | DealScorer regression (5-signal synthesis) |
| `test_board_room_formatter.py` | Board Room GO/NO-GO formatter broken |

---

## Gate Status Dashboard

| Range | Count | Status |
|-------|-------|--------|
| GATE-1 to GATE-56 | 56 | ✅ ALL PASSED |
| GATE-58 to GATE-90 | 33 | ✅ ALL PASSED |
| GATE-91 to GATE-95 | 5 | 🟡 CONDITIONAL — live Docker + deed data needed |
| GATE-96 to GATE-143 | 48 | ✅ ALL PASSED |
| GATE-144 to GATE-162 | 19 | ✅ ALL PASSED |
| GATE-163 to GATE-164 | 2 | 🔵 PLANNED (Sprint 163-164) |
| **Total passed** | **157** | **of 162 coded gates** |

**🟡 Conditional gates close when:** `docker compose up -d` + drop Form17 PDFs + `scripts/check_conditional_gates.py`

---

## Coverage Gaps (Unit-Tested Only — Need Integration Validation)

These components have unit tests with mocked DB but no live-stack integration test yet. Sprint 164 closes this for the highest-priority items.

| Component | Unit Tests | Missing |
|-----------|------------|---------|
| ParcelGraph materialization job | `test_gate159.py` (importable) | Live upsert into `parcel_graph_edges` |
| Weekly investor digest | `test_gate160.py` (mocked) | Live Obsidian write + Telegram send |
| Intelligence calibration snapshot | `test_gate157.py` (mocked) | Live `calibration_snapshots` insert |
| Digest quality check | `test_gate158.py` (mocked) | Live `agent_runs` event_type filter |
| STRR geometry centroid | `test_gate162.py` (mocked) | Live `micro_markets` geometry query |
| Deal score live PSF | `test_gate161.py` (mocked) | Real `registered_transactions` PSF avg |

---

*This file is updated by Sprint 164 T-1510 with actual test run results. Structure defined by TASK_QUEUE.md Sprint 164 spec.*
