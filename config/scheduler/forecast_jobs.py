"""
RE_OS — Forecast Jobs (Sprint 139, GATE-139)
─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ───
Weekly update_actuals + record_prediction for PSF forecast ledger.

Schedule: Monday 06:00 UTC. Misfire grace: 1h.
Overlap guard: uses a module-level flag to prevent concurrent runs
(Docker single-scheduler constraint — no cross-container race).

Prometheus: prediction_records_total per market.
"""

from collections.abc import Callable
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from config.settings import TARGET_MARKETS

__all__ = ["run_update_actuals", "run_accuracy_threshold_review", "register_jobs"]

try:
    from prometheus_client import Counter as _PromCounter
    _prediction_records = _PromCounter(
        "prediction_records_total",
        "Prediction ledger records created",
        ["market", "horizon_tier"],
    )
except ImportError:
    _prediction_records = None

_JOB_RUNNING = False
_JOB_LOCK_MSG = "[ForecastJobs] update_actuals already running, skipping concurrent invocation"


def run_update_actuals():
    """Monday 06:00 UTC: backfill actual PSF for due predictions, then record next forecast.

    Overlap guard ensures only one instance runs even if the job is
    triggered while still executing (misfire or container restart).
    """
    global _JOB_RUNNING
    if _JOB_RUNNING:
        logger.warning(_JOB_LOCK_MSG)
        return

    _JOB_RUNNING = True
    try:
        _do_update_actuals()
    finally:
        _JOB_RUNNING = False


def _do_update_actuals():
    """Core execution body — separate from overlap guard for testability."""
    from utils.prediction_tracker import update_actuals, record_prediction
    from utils.psf_forecaster import PSFForecaster

    markets = [m.strip() for m in TARGET_MARKETS]
    logger.info("[ForecastJobs] Running update_actuals for {} markets", len(markets))

    for market in markets:
        try:
            updated = update_actuals(market)
            logger.info("[ForecastJobs] {}: updated {} actuals", market, updated)
        except Exception as exc:
            logger.warning("[ForecastJobs] update_actuals failed for {}: {}", market, exc)

        try:
            forecaster = PSFForecaster()
            fc = forecaster.forecast(market)
            if fc.status == "ok" and fc.data_points >= 4:
                rec_id = record_prediction(
                    market=market,
                    psf=fc.forecast_6m,
                    horizon_weeks=26,
                    horizon_months=6,
                    model_version=fc.model_version,
                )
                if _prediction_records is not None:
                    _prediction_records.labels(market=market, horizon_tier="long").inc()
                logger.info(
                    "[ForecastJobs] {}: recorded prediction id={} psf={} (6m, horizon_weeks=26)",
                    market, rec_id, fc.forecast_6m,
                )

                short_rec_id = record_prediction(
                    market=market,
                    psf=fc.current_psf,
                    horizon_weeks=4,
                    horizon_months=1,
                    model_version="v1_4wk",
                )
                if _prediction_records is not None:
                    _prediction_records.labels(market=market, horizon_tier="short").inc()
                logger.info(
                    "[ForecastJobs] {}: recorded short prediction id={} psf={} (4wk, v1_4wk)",
                    market, short_rec_id, fc.current_psf,
                )
        except Exception as exc:
            logger.warning("[ForecastJobs] record_prediction failed for {}: {}", market, exc)


def run_accuracy_threshold_review():
    """Monthly on 1st at 10:00 UTC: review 4-week MAPE across all markets.

    Fires Discord alerts when:
    - MAPE > 15% → recommends recalibration.
    - MAPE < 5% for all markets with ≥10 actuals → confirms calibration.
    Single DB pass to avoid N+1 queries across markets.
    """
    from utils.db import get_engine as _ge
    from sqlalchemy import text as _t
    from utils.prediction_tracker import compute_mape
    from utils.discord_notifier import send_ops_alert
    from config.settings import TARGET_MARKETS

    markets = [m.strip() for m in TARGET_MARKETS]
    alerts: list[str] = []
    all_ok = True
    min_samples = 10

    # Single DB pass: collect MAPE + actuals counts per market
    market_stats: dict[str, dict] = {}
    for market in markets:
        try:
            with _ge().connect() as conn:
                mape = compute_mape(market, min_samples=3, model_version="v1_4wk", conn=conn)
                n_actuals = conn.execute(
                    _t("""SELECT COUNT(*) FROM prediction_ledger_psf
                           WHERE market = :market AND model_version = 'v1_4wk'
                           AND actual_psf IS NOT NULL"""),
                    {"market": market},
                ).scalar() or 0
            market_stats[market] = {"mape": mape, "n_actuals": n_actuals}

            if mape is not None and mape > 15.0:
                alerts.append(
                    f"Model recalibration needed: {market} 4wk MAPE = {mape}% "
                    f"(target <15%). Review PSFForecaster data quality."
                )
                all_ok = False
        except Exception as exc:
            logger.warning("[AccuracyReview] compute_mape failed for {}: {}", market, exc)

    if alerts:
        for alert in alerts:
            send_ops_alert("accuracy_threshold_breach", alert)
        logger.info("[AccuracyReview] {} high-MAPE alerts sent", len(alerts))

    if all_ok:
        total_actuals = sum(ms.get("n_actuals", 0) for ms in market_stats.values())
        if total_actuals >= min_samples:
            send_ops_alert(
                "accuracy_threshold_calibrated",
                f"Model well-calibrated: all markets 4wk MAPE < 5% ({total_actuals} total actuals).",
            )
            logger.info("[AccuracyReview] Calibrated alert sent — all markets < 5% MAPE")


def register_jobs(scheduler: BlockingScheduler, safe_job: Callable[..., object]) -> None:
    scheduler.add_job(
        lambda: safe_job(run_update_actuals, "update_actuals"),
        CronTrigger(day_of_week="mon", hour=6, minute=0),
        id="update_actuals",
        name="Weekly PSF Forecast Ledger — backfill actuals + record new predictions (Mon 06:00 UTC)",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        lambda: safe_job(run_accuracy_threshold_review, "accuracy_threshold_review"),
        CronTrigger(day=1, hour=10, minute=0),
        id="accuracy_threshold_review",
        name="Monthly MAPE threshold review — Discord alerts on drift (1st 10:00 UTC)",
        misfire_grace_time=7200,
    )
