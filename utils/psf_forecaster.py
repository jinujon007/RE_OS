"""
RE_OS — PSF Forecaster (Tier 3 — PSF Forecasting)
mlforecast + LightGBM monthly PSF forecasting with walk-forward validation.
Requires >=6 months of project_snapshots data.
Gracefully degrades when data insufficient.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from loguru import logger

__all__ = ["ForecastResult", "PSFForecaster", "_send_mape_alert", "_MAPE_THRESHOLD"]


_MAPE_THRESHOLD = 15.0


def _send_mape_alert(market: str, mape: float, direction: str, next_3mo_avg: float | None) -> None:
    if mape > _MAPE_THRESHOLD:
        try:
            from utils.discord_notifier import send
            next_str = f"₹{next_3mo_avg:,.0f}" if next_3mo_avg is not None else "N/A"
            send("bd_opportunities",
                 f"PSF Forecast Warning — {market}",
                 f"MAPE of {mape:.1f}% exceeds 15% threshold. "
                 f"Direction: {direction}. "
                 f"Next 3mo avg: {next_str}. "
                 f"Recommendation: review forecast inputs, check data quality.")
        except Exception as exc:
            logger.warning("[PSFForecaster] MAPE alert failed: {}", exc)


@dataclass
class ForecastResult:
    market: str = ""
    forecast_months: list[dict] = None
    mape: Optional[float] = None
    last_observed_psf: Optional[float] = None
    next_3mo_avg: Optional[float] = None
    direction: str = "stable"
    n_observations: int = 0
    error: Optional[str] = None
    trained_at: str = ""
    status: str = "ok"
    months_available: int = 0
    
    def __post_init__(self):
        if self.forecast_months is None:
            self.forecast_months = []


class PSFForecaster:
    """Train and predict monthly PSF trends using mlforecast + LightGBM.
    
    Requires >=6 monthly data points. Falls back to simple moving average
    when mlforecast/LightGBM unavailable or data insufficient.
    """
    
    _MIN_OBSERVATIONS = 6
    _FORECAST_HORIZON = 3
    
    def train(self, market: str, force: bool = False) -> ForecastResult:
        """Train a forecast model for a market and predict next 3 months.
        
        Args:
            market: Market name.
            force: If True, train even if less than MIN_OBSERVATIONS.
            
        Returns:
            ForecastResult with predictions or fallback MA.
        """
        result = ForecastResult(market=market, trained_at=datetime.now(timezone.utc).isoformat())
        
        try:
            from utils.db import get_engine
            from sqlalchemy import text
            
            with get_engine().connect() as conn:
                months_row = conn.execute(
                    text("""
                        SELECT COUNT(DISTINCT DATE_TRUNC('month', snapshot_date))
                        FROM project_snapshots ps
                        JOIN micro_markets m ON m.id = ps.micro_market_id
                        WHERE m.name ILIKE :m
                    """),
                    {"m": f"%{market}%"},
                ).scalar() or 0
            result.months_available = months_row
            
            if months_row < self._MIN_OBSERVATIONS and not force:
                result.status = "skipped"
                result.error = f"insufficient_data: {months_row}/{self._MIN_OBSERVATIONS} months"
                logger.warning(
                    "[PSFForecaster] Skipped for {} — only {}/{} months of snapshots available",
                    market, months_row, self._MIN_OBSERVATIONS,
                )
                return result
            
            with get_engine().connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT DATE_TRUNC('month', snapshot_date) AS month,
                               ROUND(AVG(avg_psf)::numeric, 0) AS avg_psf
                        FROM project_snapshots ps
                        JOIN micro_markets m ON m.id = ps.micro_market_id
                        WHERE m.name ILIKE :m AND ps.avg_psf IS NOT NULL
                        GROUP BY DATE_TRUNC('month', snapshot_date)
                        ORDER BY month
                    """),
                    {"m": f"%{market}%"},
                ).fetchall()
            
            import pandas as pd
            import numpy as np
            
            df = pd.DataFrame([
                {"ds": r[0], "y": float(r[1])}
                for r in rows
                if r[0] is not None and r[1] is not None
            ])
            # Guard: drop NaN/inf in target before training
            df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["y"])
            
            result.n_observations = len(df)
            result.last_observed_psf = float(df["y"].iloc[-1]) if not df.empty else None
            
            if len(df) < self._MIN_OBSERVATIONS:
                # Fallback: 3-month moving average
                ma = df["y"].rolling(window=min(3, len(df))).mean().iloc[-1]
                result.forecast_months = [
                    {"month": (datetime.now() + timedelta(days=30 * i)).strftime("%Y-%m"),
                     "predicted_psf": round(float(ma), 2)}
                    for i in range(1, self._FORECAST_HORIZON + 1)
                ]
                result.direction = "stable"
                logger.info("[PSFForecaster] {}: using MA fallback (n={})", market, len(df))
                return result
            
            try:
                from mlforecast import MLForecast
                from lightgbm import LGBMRegressor
                
                fcst = MLForecast(
                    models={"lgbm": LGBMRegressor(verbose=0, silent=True)},
                    freq="MS",
                    lags=[1, 2, 3, 6],
                    date_features=["month", "quarter"],
                )
                
                fcst.fit(df)
                predictions = fcst.predict(self._FORECAST_HORIZON)
                
                for i, (_, row) in enumerate(predictions.iterrows()):
                    raw_pred = float(row["lgbm"])
                    if np.isnan(raw_pred) or np.isinf(raw_pred):
                        raw_pred = result.last_observed_psf or 5000.0
                    raw_pred = max(500.0, min(raw_pred, 50000.0))
                    result.forecast_months.append({
                        "month": row.name.strftime("%Y-%m") if hasattr(row.name, "strftime") else str(row.name)[:7],
                        "predicted_psf": round(raw_pred, 2),
                    })
                
                # Walk-forward validation
                wf_result = self.walk_forward_validate(df)
                result.mape = wf_result.get("mape")
                
                # Direction
                if len(result.forecast_months) >= 2:
                    first = result.forecast_months[0]["predicted_psf"]
                    last = result.forecast_months[-1]["predicted_psf"]
                    if last > first * 1.03:
                        result.direction = "up"
                    elif last < first * 0.97:
                        result.direction = "down"
                    else:
                        result.direction = "stable"
                
                # Next 3mo avg
                if result.forecast_months:
                    result.next_3mo_avg = round(
                        sum(m["predicted_psf"] for m in result.forecast_months) / len(result.forecast_months), 2
                    )

            except ImportError:
                logger.debug("[PSFForecaster] mlforecast/LightGBM unavailable — using MA fallback (n={})", len(df))
                ma = df["y"].rolling(window=3).mean().iloc[-1] if len(df) >= 3 else df["y"].mean()
                result.forecast_months = [
                    {"month": (datetime.now() + timedelta(days=30 * i)).strftime("%Y-%m"),
                     "predicted_psf": round(float(ma), 2)}
                    for i in range(1, self._FORECAST_HORIZON + 1)
                ]
                result.direction = "stable"

            if result.mape is not None:
                _send_mape_alert(market, result.mape, result.direction, result.next_3mo_avg)

            logger.info("[PSFForecaster] {}: trained (n={}, MAPE={}, direction={})",
                       market, len(df), f"{result.mape:.1f}%" if result.mape else "N/A", result.direction)
            
        except Exception as exc:
            logger.warning("[PSFForecaster] Failed for {}: {}", market, exc)
            result.error = str(exc)
        
        return result
    
    def walk_forward_validate(self, df) -> dict:
        """Walk-forward validation: train T-6mo → validate T-3mo → test T.
        
        Returns:
            dict with mape (float or None), n_windows.
        """
        try:
            import pandas as pd
            import numpy as np
            from mlforecast import MLForecast
            from lightgbm import LGBMRegressor
            
            if len(df) < 9:
                return {"mape": None, "n_windows": 0, "note": "need ≥9 months"}
            
            errors = []
            for i in range(6, len(df) - 3, 3):
                train = df.iloc[:i]
                test = df.iloc[i:i+3]
                
                if len(train) < 6 or len(test) < 1:
                    continue
                
                fcst = MLForecast(
                    models={"lgbm": LGBMRegressor(verbose=0, silent=True)},
                    freq="MS",
                    lags=[1, 2, 3],
                )
                fcst.fit(train)
                preds = fcst.predict(len(test))
                
                for j, (_, pred_row) in enumerate(preds.iterrows()):
                    if j < len(test):
                        actual = test.iloc[j]["y"]
                        predicted = pred_row["lgbm"]
                        if actual and actual > 0:
                            ape = abs(actual - predicted) / actual * 100
                            errors.append(ape)
            
            if errors:
                return {"mape": round(float(np.mean(errors)), 2), "n_windows": len(errors)}
            return {"mape": None, "n_windows": 0}
        except Exception as exc:
            logger.debug("[PSFForecaster] Walk-forward failed: {}", exc)
            return {"mape": None, "n_windows": 0, "error": str(exc)}
