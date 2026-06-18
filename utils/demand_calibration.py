"""
RE_OS — Demand Coefficient Calibration (GATE-94 T-1154 + GATE-109 T-1233)

Derives the hires→housing-units coefficient using the Manyata Tech Park backcast
method: compare employment ramp (public estimates by year) against registered
transaction velocity in Yelahanka hobli villages.

Two methods:
  - DemandCalibration.run()            — legacy median-ratio approach (GATE-94)
  - run_manyata_backcast(engine)       — OLS linear regression with R²≥0.6 gate (GATE-109)

Outputs a CalibrationResult with coefficient, confidence band, and verdict.
Until calibration passes (R² ≥ 0.6), DemandIntel outputs carry [UNCALIBRATED].
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from loguru import logger
from sqlalchemy.engine import Engine


# ── Manyata employment ramp — public estimates by year ──────────────────────
# Sources: JLL India reports, Manyata annual reports, CREDAI Karnataka,
# NASSCOM GCC report. Phase 1 (2016-2018): ~8,000 seats. Phase 2 (2018-2020):
# ~25,000. Phase 3 (2020-2023): ~49,000. Phase 4 (2023-2025): ~65,000.
_MANYATA_EMPLOYMENT: dict[int, int] = {
    2016: 2000,
    2017: 5000,
    2018: 8000,
    2019: 15000,
    2020: 25000,
    2021: 32000,
    2022: 40000,
    2023: 49000,
    2024: 58000,
    2025: 65000,  # estimated
}

# Surrounding villages whose transaction activity is influenced by Manyata.
# These are the first residential catchments for Manyata employees.
_SURROUNDING_VILLAGES: list[str] = [
    "Nagawara",
    "Thanisandra",
    "Hebbal",
    "Byatarayanapura",
    "Kodigehalli",
    "Jakkur",
    "Yelahanka",
]

# Seed coefficient: 350 units per 1,000 jobs (pre-calibration estimate)
_SEED_COEFFICIENT: float = 350.0
_SEED_CONFIDENCE: float = 50.0  # ±50% pre-calibration


@dataclass
class CalibrationResult:
    coefficient: float = _SEED_COEFFICIENT
    confidence_pct: float = _SEED_CONFIDENCE
    data_points: int = 0
    method: str = "manyata_backcast"
    verdict: str = "UNCALIBRATED"
    detail: str = "Insufficient registered_transactions data for Manyata backcast"
    last_checked: str = ""

    @property
    def status(self) -> str:
        """Alias for verdict — used in GATE-109 assertions."""
        return self.verdict


class DemandCalibration:
    """Derives the hires→housing-units coefficient using Manyata backcast."""

    def run(self) -> CalibrationResult:
        """Execute the calibration and return result.

        Queries registered_transactions for Manyata-surrounding villages,
        computes incremental absorption per year, and fits the coefficient.
        """
        result = CalibrationResult(last_checked=date.today().isoformat())
        try:
            from utils.db import get_engine
            from sqlalchemy import text

            engine = get_engine(pool_size=1, max_overflow=0)
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT EXTRACT(YEAR FROM reg_date) AS yr,
                               COUNT(*) AS txn_count,
                               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY psf) AS median_psf
                        FROM registered_transactions
                        WHERE village ILIKE ANY(:villages)
                          AND reg_date >= '2016-01-01'
                          AND deed_type IN ('Sale', 'Sale Deed', 'Absolute Sale')
                          AND consideration_inr >= 100000
                        GROUP BY yr
                        ORDER BY yr
                    """),
                    {"villages": [f"%{v}%" for v in _SURROUNDING_VILLAGES]},
                ).fetchall()

            if not rows:
                result.detail = (
                    "No registered_transactions found for Manyata-surrounding villages"
                )
                return result

            self._compute_coefficient(rows, result)
            return result

        except Exception as exc:
            result.detail = f"Calibration query failed: {exc}"
            logger.debug("[DemandCalibration] query error: {}", exc)
            return result

    def _compute_coefficient(
        self,
        rows: list,
        result: CalibrationResult,
    ) -> None:
        """Fit hires→units coefficient from transaction data.

        Algorithm: For each year with registered transaction data, estimate
        housing units absorbed = txn_count * 0.60. The 0.60 multiplier
        represents the estimated fraction of transactions that are ≤1,200 sqft
        residential units (as opposed to large parcels, commercial, or other
        deed types) in Manyata's surrounding residential catchment. Source:
        JLL India Residential Market Update 2024 — Bengaluru's north-eastern
        submarket averages 55-65% apartment-sized transactions.
        """
        txn_by_year: dict[int, int] = {}
        for r in rows:
            yr = int(r[0])
            txn_by_year[yr] = int(r[1])

        result.data_points = len(txn_by_year)

        if len(txn_by_year) < 2:
            result.detail = f"Only {len(txn_by_year)} years of data — need ≥2"
            return

        hires_per_year: list[int] = []
        units_per_year: list[int] = []
        for yr in sorted(txn_by_year.keys()):
            txns = txn_by_year[yr]
            housing_units = int(txns * 0.60)
            units_per_year.append(housing_units)

            if yr in _MANYATA_EMPLOYMENT:
                prev_yr = _MANYATA_EMPLOYMENT.get(yr - 1, 0)
                hires_per_year.append(_MANYATA_EMPLOYMENT[yr] - prev_yr)
            else:
                hires_per_year.append(0)

        # Fit coefficient
        ratios: list[float] = []
        for h, u in zip(hires_per_year, units_per_year):
            if h > 0:
                ratios.append(u / h * 1000)

        if not ratios:
            result.detail = "Could not compute any years with positive hires"
            return

        import statistics

        coefficient = statistics.median(ratios)
        if len(ratios) >= 3:
            stdev = statistics.stdev(ratios) if len(ratios) >= 2 else 0.0
            confidence = min(stdev / max(coefficient, 1), 1.5) * 100
        else:
            confidence = _SEED_CONFIDENCE

        result.coefficient = round(coefficient, 1)
        result.confidence_pct = round(confidence, 1)

        if confidence < 30.0 and result.data_points >= 4:
            result.verdict = "CALIBRATED"
            result.detail = (
                f"Manyata backcast complete: {result.coefficient} units/1k jobs "
                f"(±{result.confidence_pct}%, {result.data_points} data points)"
            )
        else:
            result.verdict = "UNCALIBRATED"
            result.detail = (
                f"Insufficient calibration precision: {result.coefficient} units/1k jobs "
                f"(±{result.confidence_pct}%, need <30%, have {result.data_points} data points)"
            )

    def apply_calibration_status(
        self,
        demand_signals: Any,
        calibration: CalibrationResult | None = None,
    ) -> None:
        """Apply calibration status to a DemandSignals instance.

        Sets calibration_status to 'CALIBRATED' if calibration passes,
        otherwise leaves the default 'UNCALIBRATED'. Wraps setattr in
        try/except to handle objects without the field.
        """
        cal = calibration or self.run()
        if cal.verdict == "CALIBRATED":
            try:
                demand_signals.calibration_status = "CALIBRATED"
            except AttributeError:
                logger.warning(
                    "[DemandCalibration] target object has no calibration_status field"
                )


# ── T-1233: Manyata Backcast — Rigorous Linear Regression ────────────────────
# Employment ramp (public estimates):
#   Infosys Manyata:    50K (2019) → 90K (2023)  (Infosys annual report)
#   Overall Manyata:  120K (2019) → 180K (2023)  (JLL India, CREDAI)
# Only overall Manyata employment is used in the OLS fit (broader signal).
# Infosys-specific ramp is retained below as a cross-check constant.
_MANYATA_INFOSYS_EMPLOYMENT: dict[int, int] = {
    2019: 50000, 2020: 60000, 2021: 72000, 2022: 82000, 2023: 90000,
}
_MANYATA_OVERALL_EMPLOYMENT: dict[int, int] = {
    2019: 120000, 2020: 135000, 2021: 150000, 2022: 165000, 2023: 180000,
}
_YELAHANKA_HOBLI_VILLAGES: list[str] = [
    "Venkatala", "Yelahanka", "Shampura", "Shettihalli", "Nesagodu",
    "Kodaseegenahalli", "Geddalahalli", "Jakkuru", "Vidyaranyapura",
    "Kogilu", "Hunasamaranahalli", "Atturu", "Dodda Nekkundi",
    "Agrahara Palya", "Chokkanahalli", "Kothanur", "Singanayakanahalli",
    "Thambuchetty Palya", "Allalasandra", "Rachenahalli",
]


def run_manyata_backcast(engine: Engine) -> CalibrationResult:
    """Run Manyata backcast regression against Yelahanka hobli deed data.

    Queries registered_transactions for Yelahanka hobli villages 2019–2023,
    computes annual deed velocity as absorption proxy, and fits a linear
    model: units_absorbed = coefficient × employment_growth.

    Returns:
        CalibrationResult with coefficient (units/1k jobs), R², verdict.
    """
    result = CalibrationResult(last_checked=date.today().isoformat())

    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT EXTRACT(YEAR FROM reg_date)::int AS yr,
                           COUNT(*)::int AS txn_count,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY psf) AS median_psf
                    FROM registered_transactions
                    WHERE village = ANY(:villages)
                      AND reg_date BETWEEN '2019-01-01' AND '2023-12-31'
                      AND deed_type IN ('Sale', 'Sale Deed', 'Absolute Sale')
                      AND consideration_inr >= 100000
                    GROUP BY yr
                    ORDER BY yr
                """),
                {"villages": _YELAHANKA_HOBLI_VILLAGES},
            ).fetchall()
    except Exception as exc:
        result.detail = f"Manyata backcast query failed: {exc}"
        return result

    if not rows:
        result.detail = (
            "No registered_transactions found for Yelahanka hobli villages 2019–2023"
        )
        return result

    import numpy as np

    txn_by_year: dict[int, int] = {int(r[0]): int(r[1]) for r in rows}
    result.data_points = len(txn_by_year)

    if len(txn_by_year) < 3:
        result.detail = (
            f"Only {len(txn_by_year)} years with deed data — need ≥3 for regression"
        )
        return result

    years_sorted = sorted(txn_by_year.keys())
    X = []
    y = []
    for yr in years_sorted:
        txns = txn_by_year[yr]
        units_absorbed = txns * 0.60  # ~60% are apartment-sized
        if yr in _MANYATA_OVERALL_EMPLOYMENT:
            base = _MANYATA_OVERALL_EMPLOYMENT.get(yr - 1, _MANYATA_OVERALL_EMPLOYMENT[yr] - 10000)
            growth = _MANYATA_OVERALL_EMPLOYMENT[yr] - base
            if growth > 0:
                X.append(growth / 1000.0)  # thousands
                y.append(units_absorbed)

    if len(X) < 3:
        result.detail = f"Only {len(X)} years with positive employment growth — need ≥3"
        return result

    X_arr = np.array(X, dtype=float)
    y_arr = np.array(y, dtype=float)

    coeff = np.polyfit(X_arr, y_arr, deg=1)
    slope = coeff[0]
    intercept = coeff[1]
    y_pred = slope * X_arr + intercept
    ss_res: float = float(np.sum((y_arr - y_pred) ** 2))
    ss_tot: float = float(np.sum((y_arr - np.mean(y_arr)) ** 2))
    r_squared = max(0.0, 1.0 - float(ss_res / max(ss_tot, 1e-10))) if ss_tot > 0 else 0.0

    result.coefficient = round(slope, 1)
    r_squared = min(r_squared, 1.0)
    confidence_pct = round((1.0 - r_squared) * 100, 1)
    result.confidence_pct = confidence_pct

    if r_squared >= 0.6:
        result.verdict = "CALIBRATED"
        result.detail = (
            f"Manyata backcast CALIBRATED: {result.coefficient} units/1k jobs "
            f"(R²={r_squared:.3f}, ±{confidence_pct}%, "
            f"{result.data_points} data points). "
            f"Sources: Manyata park 120K→180K 2019–2023 (JLL India, CREDAI); "
            f"Infosys 50K→90K (Infosys annual report)."
        )
    else:
        result.verdict = "INSUFFICIENT_FIT"
        result.detail = (
            f"Manyata backcast INSUFFICIENT_FIT: {result.coefficient} units/1k jobs "
            f"(R²={r_squared:.3f}, need ≥0.6, ±{confidence_pct}%). "
            f"Sources: Manyata park 120K→180K 2019–2023 (JLL India, CREDAI); "
            f"Infosys 50K→90K (Infosys annual report). "
            f"Keeping [UNCALIBRATED] label."
        )

    return result


# ── Convenience ─────────────────────────────────────────────────────────────


def get_calibration_status() -> str:
    """Quick check: returns 'CALIBRATED' or 'UNCALIBRATED'."""
    cal = DemandCalibration()
    result = cal.run()
    return result.verdict
