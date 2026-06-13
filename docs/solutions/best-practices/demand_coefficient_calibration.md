# Demand Coefficient Calibration v0 — Manyata Backcast Method

**GATE-94, T-1154 | 2026-06-13 | Status: UNCALIBRATED**

## Objective

Derive the **hires→housing-units coefficient** — the relationship between GCC/tech
employment growth and incremental residential demand in North Bengaluru micro-markets.
This coefficient converts observed hiring momentum (from Naukri snapshots, GCC
announcements, news) into quantifiable housing-unit demand — the missing link between
"Company X is hiring 5,000 people" and "therefore N units of housing will be absorbed
over Y months."

## Method: Manyata Tech Park Backcast (2016–2023)

Manyata Tech Park is the ideal calibration case because:
- **7+ million sqft** completed office space across its first 3 phases (~49,000 seats)
- **Single corridor** (Nagawara → Hebbal → Thanisandra) — minimal geographic noise
- **Employment ramp publicly documented** via company announcements, JLL/CREDAI reports
- **Registered transaction history available** via Kaveri for surrounding villages
  (Nagawara, Thanisandra, Hebbal, Byatarayanapura)

### Steps

1. **Employment ramp:** Collect phased employment ramp by year (2016 foundation →
   8,000 by 2018 → 25,000 by 2020 → 49,000 by 2023).
2. **Transaction velocity:** For the same period, extract monthly registered transaction
   count and median PSF for the 4 surrounding villages from `registered_transactions`.
3. **Absorption calculation:** Derive annual housing units absorbed from transaction
   counts, using average unit size (1,200 sqft for premium segment, 800 sqft for
   mid-segment).
4. **Coefficient fit:** Compute ratio of incremental housing units per 1,000 new jobs.
   Expected range: 250–450 units per 1,000 jobs (25–45% of new hires buying/renting
   locally).

### Formula

```
Hires→Units Coefficient = ΔHousingUnits / ΔEmployment × 1,000

Where:
  ΔHousingUnits = Annual absorption in surrounding villages
  ΔEmployment = Announced headcount additions at Manyata Park in same year
```

### Current Status

- **Seed estimate (pre-calibration):** 350 units per 1,000 jobs (assumed midpoint)
- **Confidence band:** ±50% (pre-calibration)
- **Required N for calibration:** ≥4 annual data points (4 years of Manyata build-out)
- **Fallback:** If `registered_transactions` has <100 rows for the 4 villages, the
  calibration verdict will be "insufficient deed history — recheck at N rows"

## Recalibration Trigger

The coefficient should be recalculated when:
- `registered_transactions` crosses 1,000 rows for the 4 villages
- A new major office park opens in a covered market (e.g., Karle Tech Park Phase 2)
- Every 12 months regardless of data volume

## Downstream Dependencies

| Component | How it uses this coefficient | Impact if mis-calibrated |
|-----------|------------------------------|--------------------------|
| `DemandIntelV2.demand_score_v2` | GCC signal weighted 0.13 | Signal too loud/quiet |
| `OpportunityEngine._timing_score` | Demand pressure → timing bonus | Wrong entry/exit timing |
| Investor Brief Section 3 | GCC hiring→demand narrative | Credibility risk |

## [UNCALIBRATED] Label

All `DemandSignals` outputs carry `[UNCALIBRATED]` until the Manyata backcast
produces a coefficient with confidence band < ±30%. This label appears in:
- `str(DemandSignals)` — visible in logs, Discord digests
- All downstream consumers (deal memo, investor brief, Board Room context)

## To Run Calibration

```python
from utils.demand_calibration import DemandCalibration
cal = DemandCalibration()
result = cal.run()  # Returns CalibrationResult with coefficient, confidence, verdict
```
