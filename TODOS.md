# RE_OS — Deferred Items

Work that was explicitly scoped out of the audit remediation (2026-05-19) and is planned for future phases.

---

## Architecture

**Redis RQ task queue (Phase 3)**
Redis is wired in `docker-compose.yml` and all env vars are set, but the RQ task queue is not yet active.
Parallel market execution requires this: `rq` worker spawning, queue-per-market, result collection.
Tracked in: `docker-compose.yml` inline comment.

**Alembic database migrations**
Schema currently lives entirely in `database/schema.sql`. No ORM models exist — raw SQLAlchemy `text()` throughout.
First migration would require manually transcribing all 174 lines of DDL.
Unblock with: define SQLAlchemy ORM models → `alembic init` → `alembic revision --autogenerate`.

---

## Security

**Dashboard authentication**
`/api/run/<market>` triggers real pipeline execution with no auth guard.
Acceptable for internal LAN use; needs HTTP Basic Auth or token before any public exposure.
Fix: Flask-Login or a simple middleware checking a `DASHBOARD_SECRET` env var.

---

## Observability

**Prometheus metrics + structlog**
Currently: loguru text logs. Phase 3 target: structured JSON logs + Prometheus counters
(pipeline runs, LLM calls per provider, DB upsert rates, scrape success rates).

---

## Versioning

**v0.1.0 git tag**
To tag the current state as v0.1.0:
```bash
git tag v0.1.0
git push origin v0.1.0
```

**GitHub branch protection**
To enable branch protection on `master`:
GitHub UI → Settings → Branches → Add rule → `master` → require PR + CI pass before merge.

**GitHub repo topics**
Suggested topics to add via GitHub UI → repository About section:
`real-estate`, `crewai`, `multi-agent`, `india`, `rera`, `bengaluru`, `market-intelligence`, `postgresql`, `postgis`

---

## Testing

**Integration tests with testcontainers**
Unit tests cover validator, llm_router, checkpointer. Full pipeline integration tests
(real PostGIS container, real DB upsert round-trip) deferred to Phase 2 remediation.
Library: `testcontainers` (Python package).
