# GATE-147 R1 Audit — Prediction Ledger Maturity

| # | Severity | File | Finding |
|---|----------|------|---------|
| C1 | CRITICAL | `utils/prediction_tracker.py:241` | f-string SQL injection vector in `compute_mape`: `f"""... {version_clause} ..."""` where `version_clause` interpolates user-supplied string. Should parameterize. |
| C2 | CRITICAL | `dashboard/routers/data.py:2484-2485` | N+1 DB pattern: `compute_mape()` called twice per market, each opens a new DB connection. 8 extra connections for 4 markets. |
| H1 | HIGH | `dashboard/routers/data.py:2485` | `compute_mape(m, model_version=None)` matches ALL versions including `v1_4wk`. Should filter to `linear_v1` for 26wk MAPE. |
| H2 | HIGH | `config/scheduler/forecast_jobs.py:119-162` | Duplicate `COUNT(*)` queries in `run_accuracy_threshold_review`: same query runs in per-market loop and again in `all_ok` block. |
| H3 | HIGH | `dashboard/templates/forecast_accuracy.html:59-68` | No retry logic, no loading skeleton, no recovery from transient API failures. |
| M1 | MEDIUM | `config/scheduler/forecast_jobs.py:123-124` | `from utils.db import get_engine` inside for-loop body. Move to function-level. |
| M2 | MEDIUM | `dashboard/routers/ops.py:2556` | Prometheus counter at module level — not testable without reloading module. |
| L1 | LOW | `tests/test_gate147.py:39-44` | Assertions `>=4` and `>=1` too loose — should assert exact counts for deterministic mock. |
