# RE_OS — Data Quality (Great Expectations)

## Purpose

Prevents bad data from reaching Stage 3 LLM synthesis. After every
DBOrganizer batch upsert, the data quality checkpoint runs 3 expectations
against the database. If any ERROR-severity expectation fails, Stage 3
is skipped for that market and a Discord alert fires.

## Active Expectations

| # | Table | Column | Expectation | Severity | Configurable |
|---|-------|--------|-------------|----------|--------------|
| 1 | `rera_projects` | `price_avg_psf` | BETWEEN 2000 AND 25000 | ERROR | `DQ_PSF_MIN`, `DQ_PSF_MAX` |
| 2 | `developers` | `name` | NOT NULL | WARN | — |
| 3 | `rera_projects` | `rera_number` | MATCHES `^(PRM\|PRM/KA)/\d{4}/` | WARN | — |

### Severity Levels

| Level | Behavior |
|-------|----------|
| **ERROR** | Stage 3 BLOCKED. Discord alert fires. Pipeline continues with next market. |
| **WARN** | Logged and alerted but does NOT block Stage 3. Intended for degradations that shouldn't halt the pipeline. |

## Schema

```
upsert pipeline (Stage 2)
  │
  ▼
DBOrganizer.run()
  ├── batch upsert records (with SAVEPOINT isolation)
  ├── stamp last_scraped_at
  ├── log run to agent_runs (status='completed')
  ├── run_data_quality_checkpoint(market)
  │     ├── query rera_projects (LIMIT 5000)
  │     ├── query developers (LIMIT 5000)
  │     └── validate 3 expectations via great_expectations.from_pandas()
  │
  ├── [SUCCESS] → proceed to Stage 3 (intel crew)
  └── [FAILURE] → log to agent_runs (status='failed')
                 → Discord alert to #re-os-health
                 → raise DataQualityError
                 → Stage 3 skipped
```

## Environment Variables

| Env Var | Default | Description |
|---------|---------|-------------|
| `DQ_PSF_MIN` | 2000 | Minimum acceptable PSF for `price_avg_psf` check |
| `DQ_PSF_MAX` | 25000 | Maximum acceptable PSF for `price_avg_psf` check |

## Adding a New Expectation

In `utils/data_quality.py`, append to `_dq_expectations`:

```python
ExpectationDef(
    column="total_units",
    table="rera_projects",
    expectation_type="expect_column_values_to_be_between",
    kwargs={"min_value": 0, "max_value": 5000},
    severity="WARN",
    description="total_units BETWEEN 0 AND 5000",
)
```

Expectation methods are from Great Expectations' PandasDataset API.
Common methods: `expect_column_values_to_be_between`, `expect_column_values_to_not_be_null`,
`expect_column_values_to_match_regex`, `expect_column_values_to_be_in_set`.

## Testing

```bash
pytest tests/test_data_quality.py -v -m unit
```

Tests cover: empty DB, PSF out of range, regex mismatch, GE not installed.
Mock `great_expectations.from_pandas()` for isolated unit tests.

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| `great_expectations` import fails (not installed) | Check skipped silently | `_lazy_import_ge()` catches ImportError; returns success=true; logged at WARNING |
| DB connection timeout during check | False positive failure — Stage 3 blocked unnecessarily | `@retry` decorator (2 attempts, exponential backoff); `OperationalError` returns success=true with error field |
| Regex too strict for real RERA numbers | False positive — legitimate projects blocked | Regex is WARN severity only (not ERROR); `severity="WARN"` means log+alert but don't block |
| Table empty on first pipeline run (no data yet) | False positive — all checks fail | `LIMIT 5000` + empty DataFrame returns success=true |
| Prometheus metrics not configured | Counter increment panics | `_increment_check_counter()` wraps in try/except — no crash |
| Discord webhook URL not set | Alert lost | `send_quality_alert` → `send()` returns false; logged at DEBUG; no pipeline impact |
| `dq_expectations` list grows stale | Missing checks after schema changes | `get_active_expectations()` API for dashboard visibility; schema.yml in dbt for column-level documentation |
| GE `.from_pandas()` API changes (GE version upgrade) | Runtime AttributeError | Only 3 methods used (all stable PandasDataset methods); tests mock GE entirely |

## Monitoring

- Prometheus metric: `data_quality_checks_total{market, status}` — incremented per checkpoint run
- Check statuses: `pass`, `fail`, `skipped`, `error`, `db_error`
- Grafana alert: `rate(data_quality_checks_total{status="fail"}[1h]) > 0`
- All check results stored in `agent_runs` with `task_type='data_quality'`

## Related

- `dbt/models/marts/schema.yml` — column-level data tests
- `docs/data_freshness.md` — source-level staleness tracking (T-788)

