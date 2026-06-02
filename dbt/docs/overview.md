---
dbt:
  name: re_os
  version: 1.0.0
---

# RE_OS — dbt Documentation

## Models

| Model | Description | Materialization |
|-------|-------------|-----------------|
| `v_market_inventory` | Per-market project counts, units, absorption rate, and listing PSF. | view |
| `v_market_brief` | Full market brief with months-of-supply, supply label, pricing floors/ceilings. | view |
| `v_developer_scorecard` | Developer performance: project count, completion rate, delays, markets active. | view |
| `v_active_projects` | Active RERA projects with developer and market names. Filtered to `is_active=true`. | view |

## Source Tables

Data sourced from PostgreSQL `re_os` database, populated by the scraper pipeline.

| Source | Description | Freshness |
|--------|-------------|-----------|
| `micro_markets` | Geographic market definitions | < 24h (warn), < 72h (error) |
| `rera_projects` | RERA-registered projects | Not enforced (incremental) |
| `developers` | Developer/promoter registry | Not enforced (static) |
| `listings` | Portal property listings | < 24h (warn), < 72h (error) |
| `kaveri_registrations` | Property registration transactions | Not enforced (incremental) |
| `igr_transactions` | IGR sale deed transactions | Not enforced (incremental) |

## Tests

All models have dbt tests defined in `models/marts/schema.yml`:

- **not_null** on all primary key and required business columns (rera_number, market, developer_name, project_name)
- **unique** on rera_number
- **accepted_values** on grade (A/B/C) and supply_label (UNDERSUPPLY/BALANCED/OVERSUPPLY/INSUFFICIENT_DATA)

## Dependencies

- `dbt-utils` — expression tests, SQL utility macros
- `dbt-expectations` — advanced data quality tests (future use)

Run `dbt deps` after cloning to install.
