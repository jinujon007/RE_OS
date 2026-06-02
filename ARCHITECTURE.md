# RE_OS — Architecture

> Deep technical reference for contributors, integrators, and reviewers.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Docker Stack — 7 Containers](#docker-stack)
3. [The 3-Stage Pipeline](#the-3-stage-pipeline)
4. [Agent Architecture](#agent-architecture)
5. [Board Room](#board-room)
6. [LLM Routing](#llm-routing)
7. [Database Schema](#database-schema)
8. [Intelligence Layer](#intelligence-layer)
9. [Agent Memory System](#agent-memory-system)
10. [Dashboard API](#dashboard-api)
11. [Observability](#observability)
12. [Scheduler](#scheduler)
13. [Security Model](#security-model)
14. [Key Design Decisions](#key-design-decisions)

---

## System Overview

RE_OS is a multi-agent AI system that automates the real estate intelligence loop:

```
scrape → validate → store → analyse → brief
```

Six specialised scraper scouts pull data from RERA Karnataka, property listing portals, developer sites, news sources, and the Kaveri property registration system. A pure-Python organizer validates and upserts records into PostGIS. An analyst agent queries pre-built DB views and produces a structured market brief. A CEO agent synthesises the brief into one strategic action.

On top of the core pipeline sits a **virtual real estate office**: a Board Room with five department heads, an Intelligence Layer with semantic search and sentiment scoring, an Agent Memory system, a FastAPI dashboard, and a full Prometheus + Grafana observability stack.

---

## Docker Stack

Seven containers, all internal except port 8050 (dashboard) and optionally 3000 (Grafana).

| Container | Image | Internal Port | Role |
|-----------|-------|---------------|------|
| `re_os_db` | `postgis/postgis:15-3.3` | 5432 | Primary datastore — 16 tables, geospatial support |
| `re_os_ollama` | `ollama/ollama:latest` | 11434 | Local LLM fallback — CUDA 12.5 GPU support |
| `re_os_redis` | `redis:7-alpine` | 6379 | Task queue (RQ) + Flask-Limiter rate-limit store |
| `re_os_agents` | custom (Dockerfile) | **8050** exposed | Runs crew pipeline + FastAPI dashboard |
| `re_os_scheduler` | custom (Dockerfile) | — | APScheduler: scheduled scraping + maintenance jobs |
| `re_os_prometheus` | `prom/prometheus:latest` | 9090 | Scrapes `/metrics` from agents every 15s |
| `re_os_grafana` | `grafana/grafana:latest` | 3000 | Pre-provisioned RE_OS dashboard |

**Networking:** all containers share the default Compose network. Only `8050` is published to the host. Postgres, Redis, and Ollama are unreachable from outside Docker.

**Non-root execution:** the `agents` and `scheduler` containers run as `re_os` (uid 1001) — not root.

---

## The 3-Stage Pipeline

```
┌─────────────────────────────────────────────┐
│  STAGE 1 — Data Crew (Scraper Agent + LLM)  │
│                                             │
│  scrape_rera         → RERA Karnataka AJAX  │
│  scrape_rera_detail  → RERA project detail  │
│  scrape_listings     → 99acres/MagicBricks  │
│  scrape_portal       → 7 portals (Scrapling)│
│  scrape_developer    → 8 developer sites    │
│  scrape_news         → Google News + ET     │
│                                             │
│  Checkpoint written per market per task.    │
│  Cache hit → skip Stage 1 entirely.         │
└─────────────┬───────────────────────────────┘
              │ raw dicts
              ▼
┌─────────────────────────────────────────────┐
│  STAGE 2 — Python Organizer (no LLM)        │
│                                             │
│  1. Load checkpoint JSON                    │
│  2. validate() — type coerce, flag ESTIMATED│
│  3. Batch upsert via SAVEPOINT pattern      │
│     (individual row failures don't abort)   │
│  4. Log run metadata to agent_runs          │
└─────────────┬───────────────────────────────┘
              │ records in PostGIS
              ▼
┌─────────────────────────────────────────────┐
│  STAGE 3 — Intel Crew (Analyst + CEO)       │
│                                             │
│  Analyst: queries v_market_brief,           │
│   v_market_inventory, v_developer_scorecard │
│   → 6 market signals                        │
│                                             │
│  CEO: synthesises → 6-section brief         │
│   Section 1: Market Pulse                   │
│   Section 2: Grade A Competition            │
│   Section 3: Distressed Developers (JD/JV)  │
│   Section 4: Signals                        │
│   Section 5: Entry Point Bands (PSF)        │
│   Section 6: Strategic Recommendation       │
└─────────────────────────────────────────────┘
```

**Checkpoint logic:** if all 6 checkpoint files for a market exist and are dated today, Stage 1 is skipped entirely. Stage 3 can then run in under 2 minutes.

**Stage 2 SAVEPOINT pattern:** each DB upsert runs inside a nested transaction (`SAVEPOINT`). A bad row rolls back only that row — the rest of the batch commits. This is critical for RERA data where individual records are often malformed.

---

## Agent Architecture

### Main Crew

```python
CEO Agent (max_iter=3, HEAVY LLM tier)
    ├── Scraper Agent    → 8 tools: 6 scouts + ScoutMemoryTool + KaveriGVTool
    ├── Analyst Agent    → 6 signal tools + IntelSearchTool (ChromaDB)
    └── Sentinel Agent   → health monitor (docker healthcheck)
```

### Board Room (separate crew, concurrent execution)

```python
Board Room (5 agents, concurrent via CrewAI Process.hierarchical)
    ├── BD Head           → absorption rate, JD/JV opportunity score
    ├── Finance Head      → FeasibilityAnalystTool + IRR model
    ├── Engineering Head  → FSI calc + Typology + GreenCoverage
    ├── Ops Head          → infrastructure score, phasing risk
    └── Legal Head        → RERAComplianceTool + ZoneRiskTool + EncumbranceTool
```

### Agent Files

| File | Role | LLM Tier |
|------|------|----------|
| `agents/ceo_agent.py` | Orchestrator + synthesis | HEAVY |
| `agents/analyst_agent.py` | DB queries + 6-signal analysis | ANALYSIS |
| `agents/scraper_agent.py` | 6-scout coordination | LIGHT |
| `agents/sentinel_agent.py` | System health monitor | LIGHT |
| `agents/architect_agent.py` | FSI + Typology + GreenCoverage | ANALYSIS |
| `agents/renderer_agent.py` | Midjourney/DALL-E prompt gen | LIGHT |
| `agents/finance_head_agent.py` | IRR model + feasibility | ANALYSIS |
| `agents/compliance_researcher_agent.py` | RERA + zone + encumbrance | ANALYSIS |
| `agents/parser_agent.py` | Standalone document parsing | LIGHT |

### Specialist Scrapers

| File | Data Source | Method |
|------|------------|--------|
| `scrapers/rera_karnataka.py` | RERA Karnataka | Playwright AJAX intercept → POST fallback |
| `scrapers/rera_detail_scout.py` | RERA project detail | Playwright session |
| `scrapers/portal_scout.py` | 99acres, MagicBricks, Housing, NoBroker, PropTiger | Scrapling (TLS-spoof + stealth Playwright) |
| `scrapers/developer_scout.py` | Brigade, Prestige, Sobha, Godrej, etc. | Scrapling Dynamic |
| `scrapers/news_scout.py` | Google News, ET Realty | requests + Gemini fallback |
| `scrapers/kaveri_karnataka.py` | Kaveri guidance values + registrations | requests + DB fallback |

**ScoutMemory** (`scrapers/scout_memory.py`): SHA-256 content hash stored in Redis. Prevents re-ingesting records that haven't changed since last run.

---

## Board Room

```
POST /api/board/run
  { "market": "Yelahanka", "pitch": "5-acre R2 site, ₹4.2 Cr/acre" }
  
  → pre-computes auto-context:
      Finance: IRR from live DB (current PSF, absorption)
      Engineering: FSI from zone/plot size
      Legal: RERA compliance + zone risk
      
  → 5 agents run concurrently (~90s total)
  
  → structured deal memo:
      BD Head:       absorption score, JD/JV fit
      Finance Head:  IRR %, land-to-revenue ratio, go/no-go
      Eng Head:      FAR, typology, green coverage
      Ops Head:      phasing risk, infra score
      Legal Head:    RERA status, zone clearance, encumbrance
```

Session history persisted to `board_sessions` table. Queryable via `GET /api/board/sessions`.

---

## LLM Routing

All routing in `config/llm_router.py`. Three tiers, thread-safe exclusion tracking.

```
HEAVY  (CEO):
  Groq llama-4-scout → Gemini 2.5 Flash → NVIDIA 405B → SambaNova 70B
  → OpenRouter 70B → Cloudflare → Ollama (local)

ANALYSIS (Analyst, Finance, Legal, Architect):
  Cerebras 8B → Groq Scout → SambaNova → Ollama

LIGHT (Scraper, News, Parser):
  Cerebras 8B → Gemini Gemma 27B → NVIDIA 70B → SambaNova → Cloudflare → Ollama
```

**Provider exclusion:** when a provider returns a rate-limit error, it is added to `_excluded_providers` (guarded by `threading.Lock`). Excluded on first rate-limit hit, cleared on first success. Prevents thundering-herd re-attempts to saturated providers within a single run.

**Cerebras context cap:** 8,192 tokens. Used only for LIGHT/ANALYSIS tiers where output is structured extraction or short queries. Never used for CEO synthesis (which needs full 3-stage context).

**Cost:** a full 3-market run (Yelahanka + Devanahalli + Hebbal) costs $0 using free-tier providers.

---

## Database Schema

16 tables, 4 views. All primary keys are UUIDs (`uuid_generate_v4()`). All tables support `ON CONFLICT ... DO UPDATE` for idempotent upserts.

```
micro_markets           — geographic anchors (PostGIS polygon + centroid)
developers              — RERA-registered promoters, grade A/B/C
rera_projects           — primary intelligence: all RERA projects
project_snapshots       — time-series: PSF, inventory per project per date
listings                — portal listings (99acres, MagicBricks, etc.)
kaveri_registrations    — IGR transaction records
guidance_values         — government circle rates per locality
regulatory_zones        — BDA zone classifications (R1, R2, C1, etc.)
overlay_constraints     — airport funnel, greenbelt, STRR, flood
infrastructure_pipeline — metro, flyover, road widening project data
market_snapshots        — daily market rollup (absorption, PSF bands)
agent_runs              — pipeline execution log + stage timings
news_articles           — scraped news with FinBERT sentiment scores
board_sessions          — Board Room evaluation history
agent_memories          — per-agent confidence-weighted memory entries
tasks                   — task board (Board Room approved actions)
```

**Pre-built analytics views:**

```sql
v_active_projects      — live RERA projects + developer grade + delay status
v_market_inventory     — absorption rate, PSF bands, months-of-supply per market
v_developer_scorecard  — developer ranking: grade, units, absorption rate
v_market_brief         — combined query ready for Analyst Agent
```

**Migrations:** managed by Alembic. Applied automatically on container start via `alembic upgrade head` in the `agents` container command.

---

## Intelligence Layer

`utils/embedder.py` — **IntelEmbedder** (ChromaDB + BGE-M3 via Ollama / sentence-transformers fallback)

```
index_intel_reports()  — chunks all reports in outputs/, embeds, stores in ChromaDB
search(query, market)  — top-K semantic retrieval + cross-encoder reranking
```

`utils/sentiment.py` — **FinBERT sentiment** via HuggingFace Inference API

```
score_headline(text)   — returns float in [-1, 1]
score_batch(texts)     — batch scoring
label_from_score(s)    — "POSITIVE" / "NEUTRAL" / "NEGATIVE"
```

**IntelSearchTool:** wraps `IntelEmbedder.search()` as a CrewAI tool. Injected into Analyst Agent's tool list. Enables the Analyst to retrieve relevant past report excerpts when forming a new brief.

**Scheduled jobs (config/scheduler.py):**
- 02:00 UTC — RERA refresh
- 04:30 IST — embedding indexing job
- 05:00 IST — sentiment scoring for unscored news articles

---

## Agent Memory System

`utils/agent_memory.py` — per-agent key-value store in the `agent_memories` table.

```python
write(agent_id, key, value, confidence=0.9)   # stores with timestamp
read(agent_id, key)                            # returns value if above confidence floor
decay()                                        # weekly: multiply all confidence by 0.85
```

Memories are injected into agent context at pipeline start. High-confidence memories (> 0.7) are prepended as established facts. Decayed memories below 0.3 are pruned.

**Weekly decay cron:** runs every Monday 03:00 IST. Prevents stale memories from contaminating current analysis.

---

## Dashboard API

FastAPI server (`dashboard/app_fastapi.py`), port 8050.

### Auth

Protected endpoints require `X-API-Key: $DASHBOARD_API_KEY` header. Read-only endpoints (GET health, markets, agents, intel) are exempt. Dual-key window: set `DASHBOARD_API_KEY_PREV` to enable zero-downtime key rotation.

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/health` | open | Stack health summary |
| GET | `/api/health/live` | open | Liveness probe (for Docker healthcheck) |
| GET | `/api/agents` | open | All agent definitions + status |
| GET | `/api/markets` | open | Active markets |
| GET | `/api/intel/cards` | open | Latest intel brief per market |
| GET | `/api/intel/search` | open | Semantic search across past reports |
| GET | `/api/board/sessions` | open | Board Room session history |
| POST | `/api/board/run` | **key** | Run Board Room on a pitch |
| POST | `/api/run/{market}` | **key** | Trigger full pipeline for market |
| GET | `/api/alerts` | open | Active Discord alert history |
| GET | `/api/tasks` | open | Task board |
| GET | `/metrics` | open | Prometheus scrape endpoint |

Rate limiting: 200/hour global, 20/min on `/api/intel/search`, 5/min on `/api/board/run`.

---

## Observability

Prometheus (`config/prometheus.yml`) scrapes `re_os_agents:8050/metrics` every 15 seconds.

**Metrics exported** (`prometheus-client`):
- `re_os_pipeline_runs_total` — counter by market, stage, status
- `re_os_stage_duration_seconds` — histogram by stage
- `re_os_records_ingested_total` — counter by source
- `re_os_llm_requests_total` — counter by provider, tier, status
- `re_os_active_agents` — gauge

Grafana (`config/grafana/`) — pre-provisioned with Prometheus datasource and RE_OS dashboard JSON (`config/grafana_dashboard.json`). Access at `http://localhost:3000` (anonymous admin).

---

## Scheduler

`config/scheduler.py` — APScheduler with Redis job store.

| Job | Schedule | What It Does |
|-----|----------|-------------|
| RERA refresh | 02:00 UTC daily | Runs Stage 1 + Stage 2 for all TARGET_MARKETS |
| Market snapshot | 06:00 IST daily | Writes daily rollup to `market_snapshots` |
| Embedding index | 04:30 IST daily | Indexes all new intel reports into ChromaDB |
| Sentiment scoring | 05:00 IST daily | Scores unscored `news_articles` rows via FinBERT |
| Memory decay | Monday 03:00 IST weekly | Applies 0.85x confidence decay to all agent memories |

Error isolation: `safe_job()` wrapper (`utils/scheduler_helpers.py`) catches and logs all exceptions — a failed job never crashes the scheduler process.

---

## Security Model

- **Secrets:** `.env` is gitignored. `.env.example` contains only placeholder strings. No secrets in code.
- **DB queries:** all queries use parameterised statements via SQLAlchemy ORM or `text()` with bound parameters. No raw f-string SQL.
- **Input validation:** all pipeline-control API endpoints validate `market` parameter against a strict whitelist in `config/settings.py`. No filesystem or subprocess operation receives unvalidated user input.
- **Non-root container:** `re_os` user (uid 1001) runs the application. No root access inside the container.
- **Network isolation:** Postgres, Redis, and Ollama ports are not published. Accessible only from within the Docker network.
- **Playwright:** runs headless inside Docker, no host network access.
- **API key rotation:** dual-key window (`DASHBOARD_API_KEY` + `DASHBOARD_API_KEY_PREV`) enables zero-downtime rotation without redeployment.
- **Secrets scanning:** `detect-secrets` runs in CI on every push.
- **Dependency audit:** `pip-audit` runs in CI on every push.

---

## Key Design Decisions

| Decision | Chosen | Rejected | Why |
|----------|--------|----------|-----|
| Market-level parallelism | `subprocess.Popen` fan-out | `ThreadPoolExecutor` | Module-global `_excluded_providers` dict breaks across threads; subprocess isolation is free |
| LLM state bus | Structured `agent_runs` events | Log polling | Log polling is non-deterministic, breaks on rotation, can't survive restarts |
| API auth scope | `before_request` exempts read-only paths | Gate all `/api/*` | Blocking read-only endpoints with an API key is a UX defect |
| gunicorn workers | `--workers 1 --threads 8` (now uvicorn) | multi-worker | Multi-worker splits `_running` dict across processes — pipeline status invisible across workers |
| Stage 2 DB writes | SAVEPOINT nested transactions | Single transaction | One bad RERA record rolling back 300 good records is unacceptable for nightly scrapes |
| Scraper resilience | Scrapling (TLS-spoof + stealth PW) + raw Playwright fallback | requests only | Portal bot-detection requires TLS fingerprint spoofing; graceful degrade preserves data |
| Embeddings | BGE-M3 via Ollama (GPU) → sentence-transformers fallback | API-only | Zero-cost; local GPU available; no quota risk on large indexing jobs |
