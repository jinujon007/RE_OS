# RE_OS — Roadmap

> All phases have verifiable exit criteria (governance gates). A phase is complete only when its gate passes.

---

## Current State — v1 Complete

| Phase | Name | Status | Gate |
|-------|------|--------|------|
| Phase 1 | Scout Division (6 scrapers) | ✅ | GATE-4 |
| Phase 2 | Dashboard (FastAPI, port 8050) | ✅ | GATE-2 |
| Phase 3 | Board Room (5 dept heads) | ✅ | GATE-10 |
| Phase 4 | Agent Memory (decay + confidence) | ✅ | — |
| Phase 5 | Engineering Dept (FSI + Typology + Green Coverage) | ✅ | GATE-12 |
| Phase 6 | Finance Dept (IRR model + feasibility) | ✅ | GATE-13 |
| Phase 7 | Discord Alerts (5 formatters) | 🟡 | GATE-14 (live Discord verification pending) |
| Phase 8 | Agent Hiring (YAML registry + dashboard hire) | ✅ | GATE-17 |
| Phase 8.5 | Intelligence Layer (ChromaDB + FinBERT + BGE-M3) | ✅ | GATE-15 |
| Phase 12 | Legal Dept (RERA compliance + zone risk + encumbrance) | ✅ | GATE-16 |
| Sprint 32–33 | HF Foundation (GPU Ollama + BGE-M3 + reranker) | ✅ | GATE-18, GATE-19 |
| Sprint 39 | Data Foundation (IGR + distressed dev + Prometheus + months-of-supply) | ✅ | GATE-25 |

---

## Near-Term — Sprints 40–45 (V1 Data Quality)

**Goal:** replace all fallback/estimated values with live data. 100% real RERA records for all three markets.

| Sprint | Focus | Key Tasks | Gate |
|--------|-------|-----------|------|
| Sprint 40 | RERA portal selector fix (Yelahanka + Hebbal live records) | Fix Playwright selector `No locality input found`; target ≥100 live records per market | GATE-51 |
| Sprint 41 | Kaveri GV portal resilience | Alternative endpoint for `kaveri.karnataka.gov.in`; replace 7 seeded values with live guidance | GATE-52 |
| Sprint 42 | Listing data completeness | PSF extraction accuracy ≥90%; dedup across 99acres/MagicBricks duplicates | GATE-53 |
| Sprint 43 | Developer intelligence depth | Complete developer profiles for Grade A; delay month calculation reliability | GATE-54 |
| Sprint 44 | Discord GATE-14 closure | Live Discord verification of RERA alert within 30s of scrape | GATE-14 |
| Sprint 45 | Data quality audit + dbt baseline | Great Expectations suite; dbt model for all 4 analytics views | GATE-56 |

---

## Medium-Term — v2 Architecture (Sprints 60–66)

**Goal:** schema-first redesign. Current schema evolved organically — v2 is designed top-down from the 5 intelligence modules.

| Sprint | Phase | Description | Gate |
|--------|-------|-------------|------|
| Sprint 60 | v2 Phase 0 | Complete 20-table schema live; Alembic migrations; all v1 data migrated | GATE-44 |
| Sprint 61 | v2 Phase 1 | Unified Ingest Engine — all 6 scraper plugins emit `RawRecord`; single validation layer | GATE-45 |
| Sprint 62 | v2 Phase 2a | 5 Intel Modules each return typed `IntelPackage`: Supply, Demand, Price, Developer, Regulatory | GATE-46 |
| Sprint 63 | v2 Phase 2b | Opportunity Engine — scores ≥5 land acquisition opportunities from live DB | GATE-47 |
| Sprint 64 | v2 Phase 3 | `/api/evaluate` — Board Room + Deal Memo + Investor Brief in one call | GATE-48 |
| Sprint 65 | v2 Phase 4 | Telegram field interface — send a plot description, receive compact go/no-go verdict | GATE-49 |
| Sprint 66 | v2 Phase 5 | Full end-to-end pipeline with feedback loop; user corrections update agent memory | GATE-50 |

---

## Ecosystem Tier Tasks (Parallel with v2)

Running in parallel with v2 Phase 0+, grouped by tier:

### Tier 1 — Financial Intelligence Depth
- Portfolio correlation + Sharpe ratio (`pyfolio`)
- Rolling IRR with scenario comparison
- Land cost sensitivity bands (±15%, ±30%)
- Comparable transaction PSF from Kaveri registrations

### Tier 2 — Data Quality Infrastructure
- dbt transformation layer for all 4 analytics views
- Great Expectations suite (≥20 checks)
- Data freshness panel per source per market

### Tier 3 — Predictive Layer
- PSF trend forecasting (LightGBM via `mlforecast`)
- Absorption rate prediction per micro-market
- Distressed developer early-warning model

### Tier 4 — Geospatial Intelligence
- OpenStreetMap amenity scoring per project location
- Walking/driving distance to metro, schools, hospitals
- BDA master plan overlay integration

---

## Deferred (Post-v2 Phase 5)

| Sprint | Focus |
|--------|-------|
| Sprint 34 | Legal PDF QA (`roberta-base-squad2` on RERA approval docs) |
| Sprint 35 | `finbert-tone` directional sentiment + CI BERTScore gate |
| Sprint 36 | QLoRA Qwen2.5-3B RERA extractor fine-tune + Ollama deploy |
| Sprint 37 | Florence-2-base vision evaluation |
| Sprint 38 | Dataset publishing decision |

---

## Long-Term Vision (12–18 months)

RE_OS is ultimately a **virtual real estate intelligence office** that operates around the clock, surfaces land acquisition opportunities before competitors identify them, and produces investor-ready analysis on demand.

The 14-phase full vision: [VISION.md](VISION.md)

Key milestones toward that vision:

- **City expansion** — Hyderabad, Chennai, Pune micro-markets
- **Multi-state RERA** — MahaRERA, TGRERA, TNRERA scrapers alongside Karnataka
- **Investor interface** — structured deal memos exportable to PDF/DOCX
- **CRM integration** — BD pipeline linked to market opportunity scores
- **Mobile alerts** — Telegram bot for field teams; go/no-go in 3 taps

---

## Governance Gates

Every sprint exit requires a passing governance gate. Gates are defined in `CLAUDE.md` and verified manually or by automated test.

**Gate pattern:**
1. Define exact success criteria before writing code
2. Implement
3. Verify criteria pass
4. Mark gate as PASSED in `CLAUDE.md`

No gate can be marked PASSED without verification. No sprint can start until the prior gate is closed.

---

*Updated: 2026-06-02 · Next gate: GATE-51 (Sprint 40)*
