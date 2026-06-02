# API Reference

Base URL: `http://localhost:8050`

Authentication: protected endpoints require `X-API-Key: <DASHBOARD_API_KEY>` header.
Read-only `GET` endpoints are open (no key required).

---

## Health

### `GET /api/health`
Returns system health summary.

```json
{
  "status": "healthy",
  "database": "ok",
  "redis": "ok",
  "ollama": "ok",
  "agents_running": 0,
  "timestamp": "2026-06-02T10:15:30Z"
}
```

### `GET /api/health/live`
Liveness probe. Returns `200 OK` if the server is up. Used by Docker healthcheck.

---

## Markets

### `GET /api/markets`
Returns all configured micro-markets.

```json
[
  { "slug": "yelahanka", "name": "Yelahanka", "priority": 1 },
  { "slug": "devanahalli", "name": "Devanahalli", "priority": 1 },
  { "slug": "hebbal", "name": "Hebbal", "priority": 1 }
]
```

---

## Intelligence

### `GET /api/intel/cards`
Latest intel brief per market. Returns the most recent CEO report text + metadata.

```json
[
  {
    "market": "yelahanka",
    "report_date": "2026-06-02",
    "brief_text": "...",
    "psf_range": { "min": 5200, "max": 9400 },
    "active_projects": 47
  }
]
```

### `GET /api/intel/search?q=<query>&market=<slug>`
Semantic search across all past intel reports using ChromaDB + BGE-M3 embeddings.

| Param | Required | Description |
|-------|----------|-------------|
| `q` | yes | Search query (e.g., `"Yelahanka Grade A PSF trend"`) |
| `market` | no | Filter to a specific market slug |

Rate limit: 20 requests/minute.

```json
{
  "results": [
    {
      "excerpt": "Grade A band is supply-heavy...",
      "source": "intel_report_20260601_0215.txt",
      "market": "yelahanka",
      "relevance": 0.82
    }
  ]
}
```

---

## Pipeline

### `POST /api/run/{market}` 🔑
Trigger a full pipeline run for a market.

| Param | Type | Description |
|-------|------|-------------|
| `market` | path | Market slug: `yelahanka`, `devanahalli`, `hebbal` |

Returns immediately with a run ID. Check status via `/api/health`.

```json
{ "run_id": "run_20260602_101530_yelahanka", "status": "started" }
```

---

## Board Room

### `GET /api/board/sessions`
All past Board Room session records.

```json
[
  {
    "session_id": "uuid",
    "market": "yelahanka",
    "pitch": "5-acre R2 site near BIAL, ₹4.2 Cr/acre",
    "created_at": "2026-06-02T09:00:00Z",
    "departments_completed": 5,
    "verdict": "GO"
  }
]
```

### `POST /api/board/run` 🔑
Run a Board Room evaluation on a land acquisition pitch.

**Request body:**
```json
{
  "market": "yelahanka",
  "pitch": "5-acre R2 plot near BIAL, target launch ₹6,500 PSF, acquire at ₹4.2 Cr/acre"
}
```

Rate limit: 5 requests/minute (each run takes ~90 seconds).

**Response:**
```json
{
  "session_id": "uuid",
  "market": "yelahanka",
  "results": {
    "bd_head": "Absorption steady at 18 units/month. JD/JV score: 3/5...",
    "finance_head": "IRR: 22.4%. Land-to-revenue: 18%. GO at ₹4.2 Cr/acre...",
    "engineering_head": "FSI: 3.25. Max typology: G+14 apartment. Green coverage: 32%...",
    "ops_head": "BIAL proximity: strong. Metro Phase 3 alignment: YES...",
    "legal_head": "RERA: CLEAR. Zone R2: compliant. No encumbrance in 180 days..."
  },
  "verdict": "GO",
  "duration_seconds": 87
}
```

---

## Agents

### `GET /api/agents`
All agent definitions — name, role, status, LLM tier, last active.

### `POST /api/agents/hire` 🔑
Hire a new specialist agent from a YAML template.

**Request body:**
```json
{
  "template": "market_specialist",
  "name": "Hebbal Specialist",
  "market": "hebbal"
}
```

---

## Alerts

### `GET /api/alerts`
Active alerts (RERA new projects, distressed developers, price movements).

```json
[
  {
    "alert_type": "new_rera_project",
    "market": "yelahanka",
    "developer": "Sobha Ltd",
    "project_name": "Sobha Sentosa Phase 2",
    "units": 240,
    "psf": 8900,
    "created_at": "2026-06-02T02:15:00Z"
  }
]
```

---

## Tasks

### `GET /api/tasks`
Task board — Board Room approved actions awaiting execution.

---

## Metrics

### `GET /metrics`
Prometheus scrape endpoint. Text format.

Key metrics:
```
re_os_pipeline_runs_total{market="yelahanka",stage="stage1",status="success"} 42
re_os_stage_duration_seconds{stage="stage1"} histogram
re_os_records_ingested_total{source="rera_karnataka"} 1247
re_os_llm_requests_total{provider="groq",tier="heavy",status="success"} 87
re_os_active_agents 0
```

---

## Error Responses

All errors return JSON:
```json
{ "error": "market 'xyz' not in TARGET_MARKETS", "status": 400 }
```

| Code | Meaning |
|------|---------|
| 400 | Bad request — invalid market, missing required field |
| 401 | Missing or invalid API key |
| 429 | Rate limit exceeded |
| 500 | Internal error — check `docker compose logs agents --tail 50` |
