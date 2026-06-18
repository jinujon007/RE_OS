# API Changelog

> **Auto-generated spec:** `docs/api-v1.json` is regenerated from FastAPI `app.openapi()` by
> `scripts/export_openapi.py`. **This file is manually maintained** — entries must be added
> when routes change. See `docs/operations.md` for the canonical workflow.

---

## Versioning Policy

| Component | Scheme | Example |
|-----------|--------|---------|
| `docs/api-v1.json` | FastAPI `version` field in `app = FastAPI(version=...)` | `2.0.0` |
| Changelog version | `<major>.<minor>` — major = breaking change, minor = additive | `v1.0`, `v1.1` |

- **Patch/formatting changes** (indentation, comments, docs-only): no version bump, just update the entry.
- **Minor** (new routes, new optional params): increment minor, add `### Added` section.
- **Major** (renamed/deleted routes, changed response shapes): increment major, add `### Changed` or `### Removed`.

---

## v1.0 — 2026-06-18

Initial auto-generated OpenAPI spec from FastAPI `app.openapi()`. Path count: 104 routes.

### Added

All routes under `/api/v1/` prefix:

**Health:**
- `GET /api/v1/health` — full health check
- `GET /api/v1/health/live` — lightweight liveness probe
- `GET /api/v1/alert/test` — send test Discord alert

**Data / Market:**
- `GET /api/v1/db/state` — DB record counts and market summary
- `GET /api/v1/db/tables` — view contents of key DB views
- `GET /api/v1/intel/cards` — market summary cards
- `GET /api/v1/intel/search` — semantic search over intel reports
- `GET /api/v1/intel/download` — download intel report
- `GET /api/v1/reports/{market}` — latest intel report text
- `GET /api/v1/market/map/{market}` — Folium map with project markers
- `GET /api/v1/market/psf-trend/{market}` — monthly PSF trend
- `GET /api/v1/market/kepler-data/{market}` — GeoJSON for Kepler.gl
- `GET /api/v1/market/accessibility` — travel-time scores
- `GET /api/v1/market/forecast/{market}` — PSF forecast (3/6/12mo)
- `GET /api/v1/market/spread/{market}` — registered-vs-ask PSF spread
- `GET /api/v1/market/supply` — pipeline supply
- `GET /api/v1/data/freshness` — per-source freshness
- `GET /api/v1/data/provenance` — live vs seed breakdown

**Memory:**
- `GET /api/v1/memory/explorer` — paginated agent memory explorer
- `GET /api/v1/memory/conflict-count` — unresolved conflict count
- `GET /api/v1/memory` — memory explorer dashboard panel

**Intelligence:**
- `GET /api/v1/demand/{market}` — demand signals
- `GET /api/v1/demand/config-split` — absorption by bedroom config
- `GET /api/v1/demand` — demand intelligence dashboard panel
- `GET /api/v1/distress/signals` — developer distress signals
- `GET /api/v1/competitive/pulse` — competitive pulse
- `GET /api/v1/gcc/events` — GCC events (GET + POST)
- `GET /api/v1/gcc/north-score` — GCC north score
- `GET /api/v1/govt/events` — govt/policy events
- `GET /api/v1/govt/north-score` — north score
- `GET /api/v1/govt/digest` — weekly govt digest
- `GET /api/v1/govt` — govt dashboard panel
- `GET /api/v1/corridor/score` — corridor scores (v2)

**Parcel:**
- `GET /api/v1/parcel/{village}/{survey_no}` — full parcel dossier
- `GET /api/v1/parcel/ownership` — ownership chain
- `GET /api/v1/parcel/villages` — villages with parcel data
- `GET /api/v1/parcel` — parcel lookup dashboard panel

**Finance:**
- `GET /api/v1/finance/cashflow` — monthly cash-flow projection

**Pipeline:**
- `POST /api/v1/run/{market}` — start pipeline
- `DELETE /api/v1/run/{market}` — stop pipeline
- `GET /api/v1/status` — pipeline running status
- `GET /api/v1/agents` — full agent state
- `POST /api/v1/agents/{agent_id}/command` — send command
- `GET /api/v1/agents/{agent_id}/actions` — list agent actions
- `GET /api/v1/sentinel/status` — sentinel run status
- `GET /api/v1/logs/stream` — SSE log stream

**Board Room:**
- `POST /api/v1/board/session` — create board session
- `GET /api/v1/board/session/{session_id}` — get board session
- `GET /api/v1/board/sessions` — list board sessions
- `POST /api/v1/board/run` — run board room
- `GET /api/v1/board` — board room dashboard panel

**Digest:**
- `GET /api/v1/digest/weekly` — weekly intel digest
- `GET /api/v1/digest/monthly` — monthly intel digest
- `POST /api/v1/digest/weekly/send` — send weekly digest to Discord
- `POST /api/v1/digest/monthly/send` — send monthly digest to Discord
- `GET /api/v1/digest` — digest dashboard panel

**Operations:**
- `GET /api/v1/ops/slo` — SLO status
- `GET /api/v1/ops/v2-readiness` — V2.0 readiness
- `POST /api/v1/ops/v2-declare` — declare V2.0
- `GET /api/v1/ops/v2` — V2 dashboard panel
- `GET /api/v1/ops/ledger` — prediction ledger (Sprint 111)
- `GET /api/v1/ops/failed-records` — dead letter queue (Sprint 108)
- `GET /api/v1/ops/kill-criteria` — automated kill-criteria audit (Sprint 102)
- `GET /api/v1/audit/log` — API audit log (Sprint 107, admin only)
- `GET /api/v1/tasks` — list tasks
- `POST /api/v1/tasks` — create task
- `PATCH /api/v1/tasks/{task_id}` — update task

**Agent Registry:**
- `GET /api/v1/registry` — list agents
- `POST /api/v1/registry` — hire agent

**Surveys / Evaluate:**
- `POST /api/v1/surveys` — create survey
- `POST /api/v1/evaluate` — start async evaluation
- `GET /api/v1/evaluate/{job_id}` — poll evaluation status
- `GET /api/v1/opportunity/queue` — ranked opportunity queue

**Deal Pipeline:**
- `POST /api/v1/deals` — create deal
- `GET /api/v1/deals` — list deals
- `PATCH /api/v1/deals/{deal_id}` — update deal

**Projects:**
- `POST /api/v1/projects` — create project
- `GET /api/v1/projects` — list projects
- `GET /api/v1/projects/{project_id}` — get project
- `PATCH /api/v1/projects/{project_id}` — update project
- `PATCH /api/v1/projects/{project_id}/status` — update project status
- `GET /api/v1/projects/{project_id}/velocity` — deal velocity
- `GET /api/v1/projects/{project_id}/tasks` — create project task
- `PATCH /api/v1/projects/{project_id}/tasks/{task_id}` — update task
- `DELETE /api/v1/projects/{project_id}/tasks/{task_id}` — delete task

**Landowner CRM:**
- `POST /api/v1/landowners` — create landowner contact
- `GET /api/v1/landowners` — list landowners
- `GET /api/v1/landowners/pipeline` — pipeline summary
- `GET /api/v1/landowners/{landowner_id}` — get landowner
- `PATCH /api/v1/landowners/{landowner_id}` — update landowner

**Portfolio:**
- `GET /api/v1/portfolio` — list LLS portfolio
- `GET /api/v1/portfolio/summary` — portfolio summary

**Content / PR:**
- `POST /api/v1/content/generate` — generate brand content
- `GET /api/v1/pr/mentions` — brand mentions + competitor launches
- `GET /api/v1/content` — content studio panel
- `GET /api/v1/pr` — PR studio panel

**Telegram:**
- `POST /api/v1/telegram/webhook` — Telegram bot webhook

**Process Audit / Shareholder / Optimizer:**
- `GET /api/v1/process-audit` — process audit panel
- `GET /api/v1/process-audit/report` — latest bottleneck report
- `POST /api/v1/shareholders/trigger` — trigger quarterly review
- `GET /api/v1/shareholders/sessions` — list sessions
- `GET /api/v1/shareholders` — shareholders panel
- `GET /api/v1/optimizer` — optimizer panel
- `GET /api/v1/optimizer/report` — latest optimizer report

**Quality:**
- `GET /api/v1/scraper/reliability` — scraper reliability scores
- `GET /api/v1/data-quality` — data quality panel
- `GET /api/v1/health/llm` — LLM provider health
- `GET /api/v1/health/backup` — last backup timestamp
- `GET /api/v1/scheduler/health` — scheduler job health

**LLM:**
- `GET /api/v1/llm/quota` — daily token usage per provider

### Changed
- All routes versioned under `/api/v1/` prefix (Sprint 106)
- Legacy `/api/{path}` routes redirect 301 to `/api/v1/{path}`
- Unified error response schema: `{error, code, request_id, docs_url}`
- ETag on 5 read-heavy endpoints: `/intel/cards`, `/market/forecast/{market}`, `/data/provenance`, `/market/spread/{market}`, `/ops/slo`
- Rate limit headers (`X-RateLimit-*`) in all responses
- RBAC middleware enforces 3-tier role model (read/write/admin) on all authenticated endpoints (Sprint 107)
- All authenticated requests logged to `api_audit_log` table (Sprint 107)

### Deprecated
- `/api/{path}` legacy endpoints — use `/api/v1/{path}`

---

## How to Add an Entry

1. After adding/removing/renaming a route, regenerate the spec:
   ```bash
   make spec
   ```
2. Add a new version heading (or append to existing version):
   ```markdown
   ## v1.1 — YYYY-MM-DD
   ### Added
   - `GET /api/v1/new/route` — description
   ### Changed
   - `POST /api/v1/changed/route` — what changed
   ```
3. Commit both `docs/api-v1.json` and this file.

See `docs/operations.md#api-spec-management` for the full workflow including CI expectations.
