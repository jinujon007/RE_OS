---
title: months_of_supply CTE Pattern in v_market_brief
date: 2026-06-02
category: docs/solutions/architecture-patterns/
module: database/schema.sql
problem_type: architecture_pattern
component: database
severity: medium
applies_when:
  - Computing a ratio metric in a PostgreSQL view where the denominator can legitimately be zero
  - The view spans markets with heterogeneous data quality (some with Kaveri data, some without)
  - A graceful NULL result is preferable to a division-by-zero error
tags:
  - months-of-supply
  - cte
  - nullif
  - v-market-brief
  - postgresql
  - zero-division
  - kaveri
  - market-health
related_components:
  - tooling
---

# months_of_supply CTE Pattern in v_market_brief

## Context

`v_market_brief` in `database/schema.sql` needed a `months_of_supply` metric —
unsold inventory divided by monthly absorption — to label each market as UNDERSUPPLY
(< 9 months), BALANCED (9–18 months), or OVERSUPPLY (> 18 months). The absorption
proxy is the monthly Kaveri registration count. The problem: some markets have no
Kaveri registration data at all, making the denominator zero and crashing the view
with a PostgreSQL division-by-zero error that terminates all market queries.

Sprint 39 (T-484) replaced the prior `sold_units / 36` approximation with actual
Kaveri transaction data and a three-CTE structure that handles all data quality
states gracefully.

## Guidance

Use a three-CTE structure — `kaveri_stats` → `market_regs` → `market_fallback` —
with `NULLIF` at the exact division site, not in a WHERE clause. NULL propagation
is the graceful outcome; division-by-zero is not.

```sql
-- database/schema.sql (v_market_brief view, relevant CTEs)

-- CTE 1: raw Kaveri registration counts
kaveri_stats AS (
    SELECT
        kr.micro_market_id,
        COUNT(*)::NUMERIC / 12.0                                    AS monthly_registrations_raw,
        COUNT(*) FILTER (
            WHERE kr.registration_date >= CURRENT_DATE - INTERVAL '12 months'
        )::NUMERIC                                                  AS registrations_12mo
    FROM kaveri_registrations kr
    GROUP BY kr.micro_market_id
),

-- CTE 2: choose best available rate; NULL if no usable data
market_regs AS (
    SELECT ks.micro_market_id,
        CASE
            WHEN ks.registrations_12mo >= 3       THEN ks.registrations_12mo / 12.0
            WHEN ks.monthly_registrations_raw * 12 >= 3 THEN ks.monthly_registrations_raw
            ELSE NULL  -- propagates to NULLIF guard downstream
        END AS monthly_registrations
    FROM kaveri_stats ks
),

-- CTE 3: RERA-based fallback when no Kaveri data at all
market_fallback AS (
    SELECT ma.market_id,
        CASE
            WHEN COALESCE(ma.total_sold, 0) > 0
            THEN ROUND(
                ma.total_unsold::NUMERIC
                / NULLIF(ma.total_sold::NUMERIC / 36.0, 0)
            , 1)
            ELSE NULL
        END AS mos_fallback
    FROM market_agg ma
)

-- Final SELECT: NULLIF prevents division-by-zero; COALESCE picks fallback
SELECT ...,
    COALESCE(
        ROUND(
            ma.total_unsold::NUMERIC
            / NULLIF(mr.monthly_registrations * 12, 0)   -- CRITICAL: prevents ÷0
            * 12
        , 1),
        mf.mos_fallback                                  -- RERA proxy fallback
    ) AS months_of_supply,
    CASE
        WHEN mr.monthly_registrations IS NOT NULL
          AND ROUND(ma.total_unsold::NUMERIC / NULLIF(mr.monthly_registrations * 12, 0) * 12, 1) < 9
          THEN 'UNDERSUPPLY'
        WHEN mr.monthly_registrations IS NOT NULL
          AND ROUND(ma.total_unsold::NUMERIC / NULLIF(mr.monthly_registrations * 12, 0) * 12, 1) <= 18
          THEN 'BALANCED'
        WHEN mr.monthly_registrations IS NOT NULL
          THEN 'OVERSUPPLY'
        WHEN mf.mos_fallback IS NOT NULL AND mf.mos_fallback < 9   THEN 'UNDERSUPPLY'
        WHEN mf.mos_fallback IS NOT NULL AND mf.mos_fallback <= 18 THEN 'BALANCED'
        WHEN mf.mos_fallback IS NOT NULL                           THEN 'OVERSUPPLY'
        ELSE 'INSUFFICIENT_DATA'
    END AS supply_label
```

## Why This Matters

`NULLIF(monthly_registrations * 12, 0)` converts zero to NULL before the division
executes. PostgreSQL evaluates `NULL / anything` as NULL — no exception is raised.
Without this guard, a market with zero Kaveri registrations causes a
`ERROR: division by zero` that terminates the entire view query, making all
markets fail simultaneously even those with valid data.

**Why WHERE clause doesn't help:** A `WHERE monthly_registrations > 0` filter
evaluates after the expression is computed. The division error occurs during the
expression evaluation pass, before filtering happens.

**Three-tier data quality cascade** in `market_regs`:
1. Prefer 12-month dated window (≥ 3 records with valid dates) — most accurate
2. Fall back to raw count / 12 if dated window has < 3 records — still usable
3. Return NULL if no usable Kaveri data — propagates gracefully to COALESCE

The RERA-based fallback CTE (`market_fallback`) then handles the NULL case using
a 36-month sell-through rate as a proxy absorption signal. Markets using this
fallback receive `supply_label = 'INSUFFICIENT_DATA'` when the fallback itself
is also NULL.

## When to Apply

Apply this pattern in any PostgreSQL view that computes a rate or ratio metric
where:
- The denominator comes from a LEFT-JOINed table that may have no rows
- The metric applies across multiple rows of varying data quality
- NULL (absence of data) is a valid and meaningful output

This pattern generalises to any market health metric that uses Kaveri or RERA
counts as a denominator — PSF per unit, absorption rate, registration velocity.

Always apply `NULLIF(denominator, 0)` at the division site, not upstream.

## Examples

**Failing pattern** — WHERE clause does not prevent division-by-zero:
```sql
-- BAD: PostgreSQL evaluates the division before applying the WHERE filter
SELECT unsold_units / monthly_reg_count AS mos
FROM market_stats
WHERE monthly_reg_count > 0   -- too late; division already evaluated
```

**Correct pattern** — NULLIF converts zero to NULL before division:
```sql
-- GOOD: NULLIF converts 0 → NULL; NULL / anything = NULL (no exception)
SELECT ROUND(unsold_units::NUMERIC / NULLIF(monthly_reg_count, 0), 1) AS mos
FROM market_stats
```

**Test this guard explicitly:** Insert a test market with no Kaveri registrations
and assert the view returns NULL (not an error):
```sql
-- Verify the guard works: this should return NULL, not raise an exception
SELECT months_of_supply, supply_label
FROM v_market_brief
WHERE micro_market = 'TestMarket_NoKaveriData';
-- Expected: months_of_supply = NULL, supply_label = 'INSUFFICIENT_DATA'
```

**Label thresholds reference:**

| months_of_supply | supply_label | Market signal |
|---|---|---|
| < 9 | UNDERSUPPLY | Strong demand; entry PSF likely rising |
| 9–18 | BALANCED | Healthy absorption; normal entry timing |
| > 18 | OVERSUPPLY | Excess inventory; CEO flags in synthesis |
| NULL (Kaveri data, no RERA fallback) | INSUFFICIENT_DATA | Flag all output as uncertain |

## Related

- [[igr-transaction-ingestion-fallback-chain]] — IGR data feeds `kaveri_registrations`
- `tests/test_months_supply.py` — 8 tests: threshold labels, NULL fallback, zero-unit guard (T-486)
- `database/schema.sql` lines 756–867 — full `v_market_brief` view definition
- `agents/analyst_agent.py` — `MarketSummaryTool` reads `months_of_supply` from view
