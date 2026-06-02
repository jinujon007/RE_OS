# RE_OS — dbt SQL Transformation Layer

## Overview

Ports 4 core views (v_market_inventory, v_market_brief, v_developer_scorecard,
v_active_projects) from raw SQL in schema.sql into version-controlled,
testable dbt models.

## Prerequisites

- `dbt-core>=1.7.0` and `dbt-postgres>=1.7.0` installed (in agents container)
- PostgreSQL `re_os_db` container running
- Profile env vars set (or defaults matching dev Docker setup)

## Environment Variables

| Env Var | Default | Purpose |
|---------|---------|---------|
| `DBT_TARGET` | `dev` | Target profile (dev/prod) |
| `DBT_POSTGRES_HOST` | `re_os_db` | PostgreSQL hostname |
| `DBT_POSTGRES_USER` | `re_os` | DB user |
| `DBT_POSTGRES_PASSWORD` | `re_os_pass` | DB password |
| `DBT_POSTGRES_PORT` | `5432` | DB port |
| `DBT_POSTGRES_DB` | `re_os` | Database name |
| `DBT_POSTGRES_SCHEMA` | `public` | Target schema |
| `DBT_THREADS` | `4` | Parallel model execution threads |

## Commands

```bash
# Run from repo root with DBT_PROFILES_DIR=./dbt

# Run all models
dbt run --profiles-dir dbt

# Run specific model
dbt run --select v_market_brief --profiles-dir dbt

# Test all models
dbt test --profiles-dir dbt

# Test specific model
dbt test --select v_market_inventory --profiles-dir dbt

# Generate documentation
dbt docs generate --profiles-dir dbt
dbt docs serve --profiles-dir dbt  # http://localhost:8080

# Check source freshness
dbt source freshness --profiles-dir dbt

# Install packages
dbt deps --profiles-dir dbt
```

## Model Lineage

```
micro_markets ──┐
rera_projects ──┤──► v_market_inventory
listings ───────┘

micro_markets ──┐
rera_projects ──┤──► v_market_brief
developers ─────┤
listings ───────┤
kaveri_registrations ┘

developers ─────┐──► v_developer_scorecard
rera_projects ──┘

rera_projects ──┐──► v_active_projects
developers ─────┤
micro_markets ──┘
```

## Tests

Defined in `models/marts/schema.yml`. Covers:
- not_null on primary key columns (rera_number, market, developer, project_name)
- unique on rera_number
- accepted_values on grade (A/B/C) and supply_label categories

Run: `dbt test --profiles-dir dbt`
