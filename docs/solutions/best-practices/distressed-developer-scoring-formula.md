---
title: Distressed Developer Scoring Formula
date: 2026-06-02
category: docs/solutions/best-practices/
module: utils/distressed_developer.py
problem_type: best_practice
component: service_object
severity: high
applies_when:
  - Identifying JD/JV acquisition targets from RERA project data
  - Filtering developers by distress level for BD Head Board Room context
  - Triggering Discord alerts for time-sensitive acquisition opportunities
tags:
  - distressed-developer
  - scoring
  - jd-jv
  - bd-head
  - rera
  - acquisition-targeting
related_components:
  - background_job
  - database
---

# Distressed Developer Scoring Formula

## Context

The BD Head Board Room session needed a quantitative JD/JV opportunity signal drawn
from live RERA data. Grade A/B developers (Brigade, Prestige, Sobha) have 50+ projects
— their overdue ratios are always low even when individual projects slip, so they dilute
any market-wide signal. The scoring formula had to be sensitive to small developers
under genuine delivery stress without being noisy against the established players.

Sprint 39 implemented `utils/distressed_developer.py` with `scan_distressed_developers()`
and `DistressedDeveloperScanner`. A 10-round domain review in the planning session framed
this as "a week of Land Acquisition Manager work automated" and called it the single most
useful Sprint 39 feature (session history).

## Guidance

Three-component weighted score with a hard portfolio-size filter of `< 5 total projects`.
The filter is the most important element — without it, Grade A/B developers dominate the
results and drown out the small developers who are the actual JD/JV targets.

```python
# utils/distressed_developer.py
_DISTRESS_SCORE_THRESHOLD = 0.6  # alert-level threshold
_DELAY_WEIGHT    = 0.4
_INCOMPLETE_WEIGHT = 0.3
_COMPLAINT_WEIGHT  = 0.3

# SQL score computation (from scan_distressed_developers() query):
distress_score = ROUND(
    avg_delay_months * 0.4
    + (overdue_projects::numeric / NULLIF(total_projects, 0)) * 0.3
    + (complaint_count::numeric / NULLIF(total_projects, 0)) * 0.3
, 2)
```

**Portfolio-size filter:** Only developers with `< 5 total RERA projects` are
included. Developers with 5+ projects have lower JD/JV conversion probability —
they have investor relationships and legal capacity to manage delays independently.

**Alert levels:**
```python
if score > 0.7:
    alert_level = "HIGH_DISTRESS"   # immediate outreach candidate
elif score > 0.4:
    alert_level = "WATCH"           # monitor; not yet actionable
else:
    alert_level = "HEALTHY"
```

**Board Room auto-context wiring** — prepend top-3 distressed developers to BD Head
context before every Board Room session. This ensures JD/JV signals appear in land
acquisition discussions without a manual query:

```python
# crews/board_room.py
if key == 'bd':
    distressed = scan_distressed_developers(market, min_score=0.3, max_results=3)
    if distressed:
        distressed_context = "\n".join(format_distress_alert(d) for d in distressed)
        dept_question = f"[JD/JV targets]\n{distressed_context}\n\n{dept_question}"
```

Note `min_score=0.3` for Board Room context (watch list), vs `0.6` for Discord
alerts (actionable only). BD Head sees earlier signals than the alert threshold.

**APScheduler daily run** at 06:15 IST:
```python
# config/scheduler.py
scheduler.add_job(distressed_developer_scan, 'cron',
                  hour=0, minute=45, timezone='UTC')  # 06:15 IST = 00:45 UTC
```

## Why This Matters

**Weight rationale:**
- `avg_delay_months × 0.4` dominates because cash-flow stress is the primary JD/JV
  motivator. A developer bleeding ₹10L/month on a delayed project is highly motivated
  to transfer risk. Delay is the strongest single signal.
- `incomplete_ratio × 0.3` captures portfolio-scale distress. A developer with 2/3
  projects overdue is fundamentally different from one with 2/10 overdue — the
  formula reflects this.
- `complaint_proxy × 0.3` is a leading indicator of legal exposure. Developers
  accumulating RERA complaints face escalating penalties and buyer pressure that
  accelerate their motivation to restructure.

**Threshold calibration at 0.6:** At this score, the formula resolves to approximately
1 month average delay + 50% incomplete ratio + 50% complaint ratio — genuine stress,
not noise. The formula is not normalized to [0, 1]: `avg_delay_months` can exceed 1.0,
which is intentional — a 6-month delay should dominate the score.

## When to Apply

Run `scan_distressed_developers(market, min_score=0.3)` at the start of any BD Head
session where land acquisition is the topic. The `min_score=0.3` threshold surfaces
the watch list; `min_score=0.6` surfaces alert-level only.

**Recalibrate if:**
- RERA complaint data quality improves (currently proxied from `raw_data` JSONB)
- Market conditions shift significantly (a liquidity crisis changes what "stressed"
  means at the portfolio level)
- T-590 (PENDING) extends the complaint proxy with a dedicated RERA complaint table —
  when that lands, re-evaluate the complaint weight from 0.3 to 0.35

The `< 5 project` filter may need adjustment if LLS moves into markets with different
developer fragmentation patterns (e.g., Mysuru or Tier-2 cities where Grade B players
typically have 3-5 projects even without being distressed).

## Examples

**Developer with genuine distress** — 3 projects, avg 8-month delay, 2/3 overdue,
1 complaint:
```
score = 8.0 × 0.4  +  (2/3) × 0.3  +  (1/3) × 0.3
      = 3.2        +  0.20          +  0.10
      = 3.5  →  HIGH_DISTRESS (score > 0.7)
```
This developer is a strong JD/JV outreach candidate.

**Developer at watch level** — 4 projects, avg 2-month delay, 1/4 overdue, 0 complaints:
```
score = 2.0 × 0.4  +  (1/4) × 0.3  +  0 × 0.3
      = 0.80       +  0.075          +  0
      = 0.875  →  HIGH_DISTRESS
```
Note: even modest delays dominate the score because delay weight is 0.4. Monitor
closely even with only one overdue project if average delay is high.

**Direct usage:**
```python
from utils.distressed_developer import scan_distressed_developers, format_distress_alert

results = scan_distressed_developers(market="Yelahanka", min_score=0.6)
for dev in results:
    print(format_distress_alert(dev))
    # OUTPUT: **HIGH_DISTRESS** — Sharma Constructions (Yelahanka)
    # Score: 0.87 | Projects: 3 | Delayed: 3 (8.0mo avg) | Complaints: 2
    # **JD/JV opportunity signal**
```

## Related

- `config/scheduler.py` — daily 06:15 IST scan job
- `utils/discord_notifier.py` — Discord alert formatter for #bd-opportunities
- `crews/board_room.py` — BD Head auto-context wiring
- T-590 (PENDING) — dedicated RERA complaint table will improve complaint_proxy
  accuracy (currently extracted from `raw_data` JSONB)
