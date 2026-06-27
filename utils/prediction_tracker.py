"""
RE_OS — Prediction Tracker (Sprint 139, GATE-139)
Tracks PSF forecasts vs actuals in prediction_ledger_psf.

Design:
  - record_prediction: inserts a forecast row with horizon in weeks + months.
  - update_actuals: for each overdue prediction, looks up the median PSF
    from project_snapshots at the due-month boundary, with fallback to
    current listings median. Fires Discord alert when abs(error) > 20%.
  - compute_mape: mean absolute percentage error over rows with actuals,
    returns None when sample count is below threshold.
"""

from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from loguru import logger
from sqlalchemy import text

__all__ = ["record_prediction", "update_actuals", "compute_mape"]

# Threshold for Discord alerts on forecast accuracy degradation
_ACCURACY_ALERT_THRESHOLD_PCT = 20.0
# Safety bounds on error_pct to prevent MAPE contamination from bad data
_MAX_ERROR_PCT = 999.0


def _validate_psf(psf: float) -> float:
    """Validate PSF value is positive and finite. Raises ValueError if not."""
    if psf is None:
        raise ValueError("predicted_psf cannot be None")
    psf_f = float(psf)
    if psf_f <= 0:
        raise ValueError(f"predicted_psf must be positive, got {psf_f}")
    if psf_f > 1_000_000:
        raise ValueError(f"predicted_psf {psf_f} exceeds sanity bound (1M)")
    return psf_f


def _compute_error_pct(predicted: float, actual: float) -> float | None:
    """Compute symmetric error percentage, clamped to _MAX_ERROR_PCT."""
    if predicted is None or actual is None or abs(predicted) < 1e-9:
        return None
    raw = (actual - predicted) / predicted * 100.0
    return max(-_MAX_ERROR_PCT, min(_MAX_ERROR_PCT, round(raw, 2)))


def _psf_at_month(conn, mm_id: int, target_date: date) -> float | None:
    """Return median PSF from project_snapshots for the month containing target_date."""
    start = target_date.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    row = conn.execute(
        text("""
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY price_min_psf) AS median_psf
            FROM project_snapshots
            WHERE micro_market_id = :mm_id
              AND snapshot_date >= :start
              AND snapshot_date < :end
              AND price_min_psf IS NOT NULL
              AND price_min_psf BETWEEN 500 AND 50000
        """),
        {"mm_id": mm_id, "start": start, "end": end},
    ).scalar()
    if row is not None:
        return float(row)
    return None


def _current_listing_median(conn, mm_id: int) -> float | None:
    """Return current median listing PSF as fallback."""
    row = conn.execute(
        text("""
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY price_psf) AS median_psf
            FROM listings
            WHERE micro_market_id = :mm_id
              AND price_psf IS NOT NULL
              AND price_psf BETWEEN 500 AND 50000
              AND (source != 'seed_estimated' OR source IS NULL)
        """),
        {"mm_id": mm_id},
    ).scalar()
    if row is not None:
        return float(row)
    return None


def _send_accuracy_alert(market: str, predicted: float, actual: float, error_pct: float) -> None:
    """Fire Discord alert when forecast error exceeds threshold."""
    try:
        from utils.discord_notifier import send_ops_alert
        detail = (
            f"[PredictionLedger] {market}: forecast accuracy alert. "
            f"Predicted ₹{predicted:,.0f}, actual ₹{actual:,.0f}, "
            f"error {error_pct:+.1f}% (threshold ±{_ACCURACY_ALERT_THRESHOLD_PCT:.0f}%)"
        )
        send_ops_alert("forecast_accuracy_degraded", detail)
    except Exception as exc:
        logger.debug("[PredictionTracker] Discord alert failed: {}", exc)


def record_prediction(
    market: str,
    psf: float,
    horizon_weeks: int = 4,
    horizon_months: int | None = None,
    model_version: str = "v1",
) -> int:
    """Insert a prediction ledger row. Returns the new row id, or -1 on failure.

    Raises ValueError if psf is <= 0 or otherwise invalid.
    """
    _validate_psf(psf)
    if horizon_months is None:
        horizon_months = max(1, round(horizon_weeks / 4.348))

    from utils.db import get_engine

    try:
        with get_engine().begin() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO prediction_ledger_psf
                        (market, model_version, predicted_psf, predicted_at,
                         horizon_weeks, horizon_months, source)
                    VALUES (:market, :model_version, :psf, :now,
                            :horizon_weeks, :horizon_months, 'psf_forecaster')
                    RETURNING id
                """),
                {
                    "market": market,
                    "model_version": model_version,
                    "psf": psf,
                    "now": datetime.now(timezone.utc),
                    "horizon_weeks": horizon_weeks,
                    "horizon_months": horizon_months,
                },
            ).scalar()
        if row is not None:
            return int(row)
        logger.warning("[PredictionTracker] record_prediction returned no id for {}/{}", market, psf)
        return -1
    except Exception as exc:
        logger.warning("[PredictionTracker] record_prediction failed for {}/{}: {}", market, psf, exc)
        return -1


def update_actuals(market: str) -> int:
    """Backfill actuals for overdue predictions. Returns count of rows updated.

    For each due prediction, queries project_snapshots for the median PSF
    at the prediction's target due month. Falls back to current listing
    median if no monthly data. Fires Discord alert if error > threshold.
    """
    from utils.db import get_engine
    now = datetime.now(timezone.utc)

    with get_engine().begin() as conn:
        mm_id = conn.execute(
            text("SELECT id FROM micro_markets WHERE name = :market"),
            {"market": market},
        ).scalar()
        if mm_id is None:
            logger.warning("[PredictionTracker] Unknown market: {}", market)
            return 0

        due = conn.execute(
            text("""
                SELECT id, predicted_psf,
                       (predicted_at + (horizon_weeks * 7 * INTERVAL '1 day'))::date AS due_date
                FROM prediction_ledger_psf
                WHERE market = :market
                  AND measured_at IS NULL
                  AND predicted_at + (horizon_weeks * 7 * INTERVAL '1 day') <= :now
                ORDER BY predicted_at
            """),
            {"market": market, "now": now},
        ).fetchall()

        if not due:
            return 0

        updated = 0
        for row in due:
            actual_psf = _psf_at_month(conn, mm_id, row.due_date)
            if actual_psf is None:
                actual_psf = _current_listing_median(conn, mm_id)
            if actual_psf is None:
                logger.info(
                    "[PredictionTracker] {} prediction {}: no PSF data available, skipping",
                    market, row.id,
                )
                continue

            predicted = float(row.predicted_psf)
            error_pct = _compute_error_pct(predicted, actual_psf)

            conn.execute(
                text("""
                    UPDATE prediction_ledger_psf
                    SET actual_psf = :actual_psf,
                        measured_at = :measured_at,
                        error_pct = :error_pct
                    WHERE id = :id
                """),
                {
                    "actual_psf": actual_psf,
                    "measured_at": now,
                    "error_pct": error_pct,
                    "id": int(row.id),
                },
            )
            updated += 1

            if error_pct is not None and abs(error_pct) > _ACCURACY_ALERT_THRESHOLD_PCT:
                _send_accuracy_alert(market, predicted, actual_psf, error_pct)

        return updated


def compute_mape(market: str, min_samples: int = 3,
                 model_version: str | None = None,
                 conn=None) -> float | None:
    """Mean absolute percentage error over all predictions with actuals.

    Returns None when fewer than min_samples rows have non-null error_pct.
    Ignores rows where error_pct exceeded safety bounds (should not occur
    with CHECK constraint, but handled defensively).
    Optionally filter by model_version to separate 4wk vs 26wk MAPE.
    Accepts optional `conn` to reuse caller's DB connection (avoids N+1).
    """
    from utils.db import get_engine

    params: dict = {"market": market, "max_err": _MAX_ERROR_PCT}
    if model_version and model_version.strip():
        params["model_version"] = model_version.strip()

    sql = """
        SELECT error_pct
        FROM prediction_ledger_psf
        WHERE market = :market
          AND actual_psf IS NOT NULL
          AND error_pct IS NOT NULL
          AND abs(error_pct) < :max_err
    """
    if model_version:
        sql += " AND model_version = :model_version"
    sql += " ORDER BY predicted_at DESC"

    engine = get_engine()

    if conn is not None:
        rows = conn.execute(text(sql), params).fetchall()
    else:
        with engine.connect() as _conn:
            rows = _conn.execute(text(sql), params).fetchall()

    n = len(rows)
    if n < min_samples:
        return None

    total = sum(abs(float(r.error_pct)) for r in rows)
    return round(total / n, 2)
