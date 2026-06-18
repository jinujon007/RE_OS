# RE_OS — Operations

## SLO Definitions

### Scheduler SLO
- **Target:** Success rate ≥ 0.95 over 7d rolling window.
- **Measurement:** `SELECT COUNT(*), SUM(CASE WHEN status='success' THEN 1 END) FROM agent_runs WHERE created_at > NOW() - INTERVAL '7 days'`
- **Breach:** If scheduler job failure rate exceeds 5% over 7 days.
- **Alert:** Prometheus alert `SchedulerJobHighFailureRate` fires at `severity=critical` after 5m of >5% failure rate.

### Board Room SLO
- **Target:** p95 response time < 90s over 7d rolling window.
- **Measurement:** `SELECT response_time_s FROM board_sessions WHERE completed_at IS NOT NULL AND created_at > NOW() - INTERVAL '7 days'` — 95th percentile.
- **Breach:** If Board Room API takes >90s for 5% of requests over 7 days.
- **Alert:** Prometheus alert `BoardRoomHighLatency` fires at `severity=warning` after 2m of p95 >90s.

## Monitoring

### Grafana Dashboards
- **Pipeline Health** (port 3000, grafana dashboard `pipeline_health`): Stage durations, scraper success rates, scheduler job health.
- **Intelligence Quality** (dashboard `intelligence_quality`): Prediction ledger hit rate, Board Room latency, PSF forecast MAE.
- **System Health** (dashboard `system_health`): DB latency, Prometheus target health, API error rate.

### Prometheus Alerting Rules
Rules defined in `prometheus/alerts.yml`, loaded by Prometheus on startup.

### SLO API
`GET /api/v1/ops/slo` (or `/api/ops/slo` → redirect) returns current SLO status for both targets. Rate limited: 30/min.

This endpoint is documented in the [auto-generated OpenAPI spec](api-v1.json). To see the full request/response schema:
```bash
python scripts/export_openapi.py --dry-run | python -c "import json,sys;d=json.load(sys.stdin);print(json.dumps(d['paths'].get('/api/v1/ops/slo',{}),indent=2))"
```
See [API Spec Management](#api-spec-management) for spec regeneration workflow.

## Alert Cooldowns

Alert suppression windows (via `AlertSuppressor`):
- OPS alerts: 4h cooldown
- Scraper alerts: 12h cooldown
- Data quality alerts: 24h cooldown
- Backup alerts: 26h cooldown

## Scheduler Health

`scheduler_heartbeat` writes a row to `agent_runs` every 30 minutes.

### Defense-in-depth monitoring (two thresholds)

| Layer | Threshold | Action | Responsibility |
|-------|-----------|--------|----------------|
| Docker healthcheck | 30 min | Container restart via `docker-compose` | `config/healthcheck.py` (exit 1 → restart) |
| Discord OPS alert | 2h via `check_heartbeat_staleness()` | Manual investigation | `config/scheduler/maintenance_jobs.py` |

The Docker healthcheck (`config/healthcheck.py`) is a three-state probe:

1. **Module import** — verifies scheduler code compiles. Exit 1 = unhealthy (restart).
2. **Heartbeat freshness** — queries `agent_runs` for a row younger than 30 minutes. Exit 1 = stale (restart).
3. **DB unreachable** — degraded pass (exit 0). DB may be in startup race; `check_heartbeat_staleness` catches persistent staleness via Discord.

The 90-minute gap between auto-restart (30 min) and ops notification (2h) is intentional:
- If a transient issue (e.g., heavy job blocks heartbeat thread for 31 min), Docker restarts the container. The restart resolves it silently — no ops distraction.
- If the scheduler is crash-looping (restarted by Docker every ~35 min but never stays up for 2h), ops gets no alert. This is an accepted gap — the pipeline data freshness floor check (`run_data_floor_check`) independently validates per-market data freshness and fires if any market's live RERA count drops below threshold.
- If the scheduler is truly dead (no restarts, no heartbeat), ops gets alerted at 2h.

### Heartbeat probe command

```bash
docker compose exec scheduler_v2 python config/healthcheck.py
echo $?  # 0 = healthy/degraded, 1 = unhealthy
```

## Telegram Webhook Registration

The Telegram bot receives deal evaluations via webhook at `/api/v1/telegram/webhook`.

### Production Setup

1. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` in `.env`.
2. Register the webhook with Telegram (run once):
   ```bash
   curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
     -d "url=https://your-domain.com/api/v1/telegram/webhook" \
     -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
   ```
3. Verify: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"` should show `has_custom_certificate: false`, `pending_update_count: 0`.

The `secret_token` is verified via `hmac.compare_digest()` on every webhook request. If `TELEGRAM_WEBHOOK_SECRET` is not set, a warning is logged and the webhook runs without secret verification (development only).

### API Key Roles

Three API key tiers control endpoint access via `X-API-Key` header:

| Role   | Env Variable              | Access                                    |
|--------|---------------------------|-------------------------------------------|
| Read   | `DASHBOARD_API_KEY_READ`  | Read-only endpoints (`/api/v1/health`, `/api/v1/market/`, etc.) |
| Write  | `DASHBOARD_API_KEY`       | Read + mutating endpoints (`/api/v1/evaluate`, `/api/v1/board/session`) |
| Admin  | `DASHBOARD_API_KEY_ADMIN` | Full access including admin endpoints (`/api/v1/ops/kill-criteria`, `/api/v1/audit/log`) |

Backward compatibility: existing single `DASHBOARD_API_KEY` maps to write role. Key rotation via `DASHBOARD_API_KEY_PREV` continues to work for all roles.

## API Spec Management

The OpenAPI spec is auto-generated from FastAPI route definitions and committed to `docs/api-v1.json`.
Current route count: 104 (as of v1.0). **Path count is NOT auto-tracked** — update the changelog manually when the route inventory changes.

### Rules
1. **Every PR that adds, removes, or renames an API route MUST:**
   - Regenerate the spec:
     ```bash
     make spec           # validates script exists, writes docs/api-v1.json
     ```
   - Add an entry to `docs/api-changelog.md` under the next version heading (see [Versioning Policy](../docs/api-changelog.md#versioning-policy))
2. **CI checks** spec drift via the `api-spec-drift` job (`.github/workflows/ci.yml`):
   - Runs `scripts/export_openapi.py --dry-run`
   - Strips the `x-generated-at` timestamp from both the live output and committed file
   - Exits 1 if files differ → developer must run `make spec` and commit `docs/api-v1.json`
3. **Workflow summary:**
   ```bash
   make spec                    # regenerate
   # ... verify, test, commit ...
   git add docs/api-v1.json docs/api-changelog.md
   ```

### Script Reference
| Flag | Behavior | Use case |
|------|----------|----------|
| *(none)* | Writes to `docs/api-v1.json` | Developer workstation |
| `--dry-run` | Prints to stdout (no file write) | CI diff, verification |
| `--help` | Prints usage and exit codes | Documentation |

Exit codes: `0`=ok, `1`=schema validation error, `2`=import/generation error.

### References
- Source: `scripts/export_openapi.py`
- Spec: `docs/api-v1.json`
- Changelog: `docs/api-changelog.md`

## Load Testing

k6 baseline load test at `tests/load/k6_baseline.js` (T-1249, recalibrated T-1288):

### CI Baseline (20 VU)

Gentle ramp optimised for CI environments. Runs as a smoke test, NOT a production benchmark.

- **Target:** 10→20 VUs over 40s hitting `/api/v1/health/live`, `/api/v1/health`, `/api/v1/status`
- **Thresholds:** `http_req_failed < 1%`, `http_req_duration p95 < 500ms`
- **Stages:** 10s warm-up (10 VUs) → 30s steady (20 VUs) → 10s cooldown
- **Run locally:** `k6 run tests/load/k6_baseline.js`
- **Run with API key:** `k6 run -e DASHBOARD_API_KEY=xxx tests/load/k6_baseline.js`
- **Run against non-default host:** `k6 run -e BASE_URL=http://other:8050 tests/load/k6_baseline.js`

### Production Benchmark (100 VU — NOT YET DEFINED)

The CI baseline confirms the app is alive and responding. A production-grade benchmark (target: 100 VU sustained over 5 min + spike test) is not yet defined. When ready, create a parallel script `tests/load/k6_production.js` with:
- Target: 100 VU sustained, p95 < 200ms
- Spike: 200 VU for 30s, p95 < 500ms
- Endpoints: read mix + POST /api/evaluate + POST /api/board/session

CI runs the baseline load test conditionally on push to main. **Note:** No k6 step is currently configured in `.github/workflows/ci.yml`. The k6 binary must be installed in the CI runner or via a k6 GitHub Action (`grafana/k6-action@v0.3.1`). Until added, run manually.

Monitor `db_pool_checkedout` and `db_pool_overflow` Grafana metrics during load to detect connection pool exhaustion.

### Redis failover

Redis pool exhaustion falls back to in-memory state — safe for up to 2 workers; increase `REDIS_MAX_CONNECTIONS` env var if running >2 workers.

Redis connection failures are self-healing:
- `_REDIS_CLIENT_INSTANCE = False` sentinel triggers automatic reconnect on next call (no container restart required)
- A background health-check loop pings Redis every 15s and restores the connection within 30s of Redis coming back online
- Pool exhaustion fires a Discord alert via `send_ops_alert("db_pool_exhausted", ...)` with 4-hour AlertSuppressor dedup

**Observability:**
- `redis_connected` Prometheus gauge (1=connected, 0=disconnected) — visible in Grafana `system_health` dashboard
- Pool exhaustion fires Discord OPS alert to `#re-os-health`; check `db_pool_checkedout` / `db_pool_overflow` / `db_pool_wait_seconds` Prometheus gauges for capacity planning

### Scheduler Jobs: Corridor Backtest

A weekly corridor backtest runs every Monday 03:00 UTC (`corridor_backtest_weekly`):
- Scores each seeded corridor (NH-44, Hebbal-Yelahanka, Doddaballapur) on transaction velocity + avg PSF within its ST_Buffer polygon (1km radius)
- Computes Spearman rank correlation between corridor score and distance-to-airport
- Kill criterion: rank correlation > 0.67 = PASS, else FAIL, INSUFFICIENT_DATA if <5 deeds
- Writes verdict to `corridor_backtest_verdicts` table
- Alerts Discord on verdict change (PASS→FAIL, FAIL→PASS, INSUFFICIENT→FAIL)

Run manually:
```bash
docker compose exec agents python scripts/run_corridor_backtest.py
docker compose exec agents python scripts/run_corridor_backtest.py --corridor nh44
```

API: `GET /api/v1/ops/corridor-backtest` returns last verdict per corridor.

### CI: No Untracked Skips Rule

Every `pytest.mark.skip` or `pytest.mark.xfail` added to the test suite must include a
trailing comment `# TRACK: <ticket-or-reason>`.

The CI job `check-no-new-skips` in `.github/workflows/ci.yml` compares the PR branch
against `origin/master` — any new line containing `pytest.mark.skip` or `pytest.mark.xfail`
without a `# TRACK:` comment will fail the build.

**Example of acceptable annotations:**
```python
@pytest.mark.skip(reason="requires torch + transformers — not installed in CI")  # TRACK: eval_florence2
@pytest.mark.skipif("not os.environ.get('DATABASE_URL')")  # TRACK: requires live DB
@pytest.mark.xfail(reason="flaky — fix pending refactor")  # TRACK: T-XXX
```

### API Audit Log

Every authenticated request is logged to the `api_audit_log` table (migration 0063).
Admin users can query via `GET /api/v1/audit/log?limit=50` (rate limited, admin only).
