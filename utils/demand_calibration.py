"""
RE_OS — Demand Coefficient Calibration v0 (GATE-94, T-1154)

Derives the hires→housing-units coefficient using the Manyata Tech Park backcast
method: compare employment ramp (public estimates by year) against registered
transaction PSF and velocity in surrounding villages.

Outputs a CalibrationResult with coefficient, confidence band, and verdict.
Until calibration passes (confidence < 30%), DemandIntel outputs carry
[UNCALIBRATED] label.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from loguru import logger


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


# ── Convenience ─────────────────────────────────────────────────────────────


def get_calibration_status() -> str:
    """Quick check: returns 'CALIBRATED' or 'UNCALIBRATED'."""
    cal = DemandCalibration()
    result = cal.run()
    return result.verdict
