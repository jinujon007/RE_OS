"""
RE_OS — PSF Forecaster (Sprint 85, GATE-85)
numpy-based linear trend forecaster for monthly median PSF.
No new dependencies — uses numpy.polyfit.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from loguru import logger

import numpy as np


__all__ = ["ForecastResult", "PSFForecaster"]


@dataclass
class ForecastResult:
    market: str = ""
    as_of: str = ""
    data_points: int = 0
    trend_direction: str = "flat"
    slope_pct_per_month: float = 0.0
    current_psf: float = 0.0
    forecast_3m: float = 0.0
    forecast_6m: float = 0.0
    forecast_12m: float = 0.0
    conf_low_3m: float = 0.0
    conf_high_3m: float = 0.0
    conf_low_6m: float = 0.0
    conf_high_6m: float = 0.0
    conf_low_12m: float = 0.0
    conf_high_12m: float = 0.0
    mae_pct: float = 0.0
    model_version: str = "linear_v1"
    status: str = "ok"

    @property
    def error_range_6m(self) -> int:
        return int(abs(self.conf_high_6m - self.conf_low_6m) / 2) if self.conf_high_6m or self.conf_low_6m else 0


class PSFForecaster:
    """Lightweight monthly PSF forecaster using numpy.polyfit.

    Requires >=4 monthly data points. Uses linear trend + sigma confidence interval.
    If >=12 months: applies 3-point centered moving average before trend fit.
    Walk-forward MAE: 1-step-ahead prediction for last 3 months.

    Retention: market_forecasts rows should be pruned after 52 weeks
    (1 year of weekly forecasts = 156 rows per market).
    """

    _MIN_OBS = 4
    _SMOOTH_THRESHOLD = 12
    _TREND_PCT_THRESHOLD = 0.5
    _CONF_SIGMA_MULTIPLIER = 1.5
    _WF_HOLDOUT = 3

    def _load_monthly_series(self, market: str) -> list[tuple[datetime, float]]:
        from utils.db import get_engine
        from sqlalchemy import text

        try:
            with get_engine().connect() as conn:
                mm_id = conn.execute(
                    text("SELECT id FROM micro_markets WHERE name = :market"),
                    {"market": market},
                ).scalar()
                if mm_id is None:
                    logger.warning("[PSFForecaster] Unknown market: {}", market)
                    return []
                rows = conn.execute(
                    text("""
                        SELECT DATE_TRUNC('month', snapshot_date) AS month,
                               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_min_psf) AS median_psf
                        FROM project_snapshots
                        WHERE micro_market_id = :mm_id AND price_min_psf > 1000
                        GROUP BY DATE_TRUNC('month', snapshot_date)
                        ORDER BY month
                    """),
                    {"mm_id": mm_id},
                ).fetchall()
            return [(r[0], float(r[1])) for r in rows if r[0] is not None and r[1] is not None]
        except Exception as exc:
            logger.warning("[PSFForecaster] _load_monthly_series failed for {}: {}", market, exc)
            return []

    def forecast(self, market: str) -> ForecastResult:
        """Generate PSF forecast for a market.

        Steps:
        1. Load monthly median PSF series from project_snapshots (PERCENTILE_CONT).
        2. If <4 points: return insufficient_data (all forecasts = current_psf).
        3. If >=12 points: apply 3-point centered moving average to smooth seasonality.
        4. Fit linear trend via numpy.polyfit(x, y, deg=1).
        5. Project 3/6/12 months forward from last observation.
        6. Compute confidence interval: sigma * 1.5 around each projection (clamped >= 0).
        7. Walk-forward MAE: hold out last 3 months, 1-step-ahead re-fitting.

        Returns ForecastResult with status 'ok', 'insufficient_data', or 'error'.
        Never raises — all exceptions caught and logged.
        """
        result = ForecastResult(
            market=market,
            as_of=datetime.now(timezone.utc).isoformat(),
        )

        try:
            series = self._load_monthly_series(market)
            result.data_points = len(series)

            if len(series) < self._MIN_OBS:
                result.status = "insufficient_data"
                result.current_psf = round(float(series[-1][1])) if series else 0.0
                result.forecast_3m = result.current_psf
                result.forecast_6m = result.current_psf
                result.forecast_12m = result.current_psf
                return result

            raw_y = np.array([v for _, v in series], dtype=float)
            result.current_psf = round(float(raw_y[-1]))

            if len(raw_y) >= self._SMOOTH_THRESHOLD:
                y = np.convolve(raw_y, [1/3, 1/3, 1/3], mode="valid")
                x = np.arange(1, len(y) + 1, dtype=float)
                last_x = float(x[-1])
                raw_used = raw_y  # keep raw for walk-forward
            else:
                y = raw_y
                x = np.arange(len(y), dtype=float)
                last_x = float(len(y) - 1)
                raw_used = y

            coeffs = np.polyfit(x, y, deg=1)
            slope, intercept = coeffs

            mean_y = float(np.mean(y))
            slope_pct = (slope / mean_y * 100) if mean_y > 0 else 0.0
            result.slope_pct_per_month = round(float(slope_pct), 4)

            if slope_pct > self._TREND_PCT_THRESHOLD:
                result.trend_direction = "rising"
            elif slope_pct < -self._TREND_PCT_THRESHOLD:
                result.trend_direction = "falling"
            else:
                result.trend_direction = "flat"

            def project(n_months):
                return float(slope * (last_x + n_months) + intercept)

            result.forecast_3m = round(project(3))
            result.forecast_6m = round(project(6))
            result.forecast_12m = round(project(12))

            y_fitted = slope * x + intercept
            sigma = float(np.std(y - y_fitted))

            for horizon, attr_low, attr_high in [
                (3, "conf_low_3m", "conf_high_3m"),
                (6, "conf_low_6m", "conf_high_6m"),
                (12, "conf_low_12m", "conf_high_12m"),
            ]:
                f_val = getattr(result, f"forecast_{horizon}m", 0)
                setattr(result, attr_low, round(max(0, f_val - self._CONF_SIGMA_MULTIPLIER * sigma)))
                setattr(result, attr_high, round(f_val + self._CONF_SIGMA_MULTIPLIER * sigma))

            # Walk-forward MAE: 1-step-ahead for last 3 months of raw data
            # Uses raw (unsmoothed) y to reflect real forecast error
            if len(raw_used) >= self._MIN_OBS + self._WF_HOLDOUT:
                errors = []
                n = len(raw_used)
                wf_x = np.arange(n, dtype=float)
                for i in range(n - self._WF_HOLDOUT, n):
                    train_x = wf_x[:i]
                    train_y = raw_used[:i]
                    wf_coeffs = np.polyfit(train_x, train_y, deg=1)
                    pred = float(wf_coeffs[0] * wf_x[i] + wf_coeffs[1])
                    actual = float(raw_used[i])
                    if actual > 0:
                        errors.append(abs(pred - actual) / actual * 100)
                result.mae_pct = round(float(np.mean(errors)), 2) if errors else 0.0

            result.status = "ok"

        except Exception as exc:
            logger.warning("[PSFForecaster] forecast failed for {}: {}", market, exc)
            result.status = "error"

        # Log falsifiable claim to prediction_ledger (GATE-93, T-1148)
        if result.status == "ok" and result.data_points >= 4:
            try:
                from utils.prediction_ledger import write_prediction_ledger
                from datetime import date, timedelta
                write_prediction_ledger(
                    source_module="psf_forecaster",
                    claim_type="psf_forecast",
                    market=market,
                    claim_text=f"{result.trend_direction} PSF trend for {market}: "
                               f"current={result.current_psf}, "
                               f"6m forecast={result.forecast_6m} ±{result.error_range_6m}",
                    falsifiable_metric=(
                        f"registered_transactions PSF median for {market} "
                        f"within {result.conf_low_6m}–{result.conf_high_6m} range"
                    ),
                    predicted_value=float(result.forecast_6m),
                    check_date=date.today() + timedelta(days=180),
                    confidence=max(0.0, min(1.0, 1.0 - (result.mae_pct or 0.0) / 100.0)),
                )
            except Exception:
                logger.debug("[PSFForecaster] prediction_ledger write skipped (non-fatal)")

        return result
