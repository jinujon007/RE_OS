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

__all__ = ["run_update_actuals", "register_jobs"]

try:
    from prometheus_client import Counter as _PromCounter
    _prediction_records = _PromCounter(
        "prediction_records_total",
        "Prediction ledger records created",
        ["market"],
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
                    _prediction_records.labels(market=market).inc()
                logger.info(
                    "[ForecastJobs] {}: recorded prediction id={} psf={} (6m, horizon_weeks=26)",
                    market, rec_id, fc.forecast_6m,
                )
        except Exception as exc:
            logger.warning("[ForecastJobs] record_prediction failed for {}: {}", market, exc)


def register_jobs(scheduler: BlockingScheduler, safe_job: Callable[..., object]) -> None:
    scheduler.add_job(
        lambda: safe_job(run_update_actuals, "update_actuals"),
        CronTrigger(day_of_week="mon", hour=6, minute=0),
        id="update_actuals",
        name="Weekly PSF Forecast Ledger — backfill actuals + record new predictions (Mon 06:00 UTC)",
        misfire_grace_time=3600,
    )
