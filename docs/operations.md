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

## Alert Cooldowns

Alert suppression windows (via `AlertSuppressor`):
- OPS alerts: 4h cooldown
- Scraper alerts: 12h cooldown
- Data quality alerts: 24h cooldown
- Backup alerts: 26h cooldown

## Scheduler Health

`scheduler_heartbeat` writes a row to `agent_runs` every 30 minutes.
If last heartbeat > 2h old, Discord OPS alert fires.

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

## Load Testing

k6 baseline load test at `tests/load/k6_baseline.js` (T-1249):

- **Target:** 10→25→50 VUs staged ramp-up over 60s hitting `/api/v1/health/live`, `/api/v1/health`, `/api/v1/status`
- **Thresholds:** `http_req_failed < 1%`, `http_req_duration p95 < 200ms`
- **Stages:** 10s warm-up (10 VUs) → 20s ramp (25 VUs) → 20s ramp (50 VUs) → 10s sustained peak
- **Run locally:** `k6 run tests/load/k6_baseline.js`
- **Run with API key:** `k6 run -e DASHBOARD_API_KEY=xxx tests/load/k6_baseline.js`
- **Run against non-default host:** `k6 run -e BASE_URL=http://other:8050 tests/load/k6_baseline.js`

CI runs this load test conditionally on push to main. Monitor `db_pool_checkedout` and `db_pool_overflow` Grafana metrics during load to detect connection pool exhaustion.

### API Audit Log

Every authenticated request is logged to the `api_audit_log` table (migration 0063).
Admin users can query via `GET /api/v1/audit/log?limit=50` (rate limited, admin only).
