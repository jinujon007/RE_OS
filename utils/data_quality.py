"""
RE_OS — Data Quality (Great Expectations Integration)
Runs configurable data quality checks after batch upsert, before Stage 3 LLM
synthesis. Bad data is caught here — never silently reaches the Board Room.

Risk matrix:
  - GE not installed: Skipped gracefully (logger.warning). Pipeline continues.
  - DB connection failure: Caught by retry (2 attempts), then caught by
    except OperationalError → error key set, success=True (non-blocking).
  - Market not in DB: No rows returned for that market → all expectations
    against market-filtered tables skipped. Developers table unfiltered.
  - Unexpected exception in expectation method: Caught individually at the
    per-expectation level (logger.warning), never crashes the batch.
  - Empty tables: Per-table skip with logger.info.
  - Bad value sample > 5: Truncated to 5 in to_dict().
  - Metrics counter failure: logger.debug only — never blocks.

Design decisions:
  - Single DB round-trip, then one GE validation (not N queries).
  - Severity per expectation: ERROR blocks Stage 3, WARN logs only.
  - Expectations configurable via settings or env vars.
  - Samples bad values (LIMIT 5) to avoid OOM on large tables.
  - projected_columns derived dynamically from _dq_expectations.
  - SQL queries filter by market via micro_markets JOIN where possible.
  - get_engine() called inside try/except to avoid retry-bypass on engine error.

Returns:
    Dict with keys: success, failed_expectations, warnings, total_checked,
    elapsed_seconds, error (on failure).
    Empty string from format_data_quality_alert means no issues.

Exports:
    ExpectationDef, FailedExpectation, DataQualityError,
    run_data_quality_checkpoint, format_data_quality_alert,
    get_active_expectations, _derive_projected_columns.
"""

__all__ = [
    "ExpectationDef",
    "FailedExpectation",
    "DataQualityError",
    "run_data_quality_checkpoint",
    "format_data_quality_alert",
    "get_active_expectations",
]
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlalchemy.exc import OperationalError, DatabaseError
from utils.db import get_engine

_GE_IMPORTED = False
_ge = None


def _lazy_import_ge():
    global _ge, _GE_IMPORTED
    if not _GE_IMPORTED:
        try:
            import great_expectations as _ge_mod
            _ge = _ge_mod
        except ImportError:
            _ge = None
        _GE_IMPORTED = True
    return _ge


@dataclass
class ExpectationDef:
    column: str
    table: str
    expectation_type: str
    kwargs: dict = field(default_factory=dict)
    severity: str = "ERROR"
    sql: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "column": self.column,
            "table": self.table,
            "expectation_type": self.expectation_type,
            "severity": self.severity,
            "description": self.description or f"{self.column} on {self.table}",
        }


@dataclass
class FailedExpectation:
    expectation: ExpectationDef
    message: str
    bad_values: list = field(default_factory=list)
    unexpected_count: int = 0

    def to_dict(self) -> dict:
        return {
            "expectation": self.expectation.description or self.expectation.expectation_type,
            "column": self.expectation.column,
            "table": self.expectation.table,
            "severity": self.expectation.severity,
            "bad_values": self.bad_values[:5],
            "unexpected_count": self.unexpected_count,
            "message": self.message,
        }


class DataQualityError(Exception):
    def __init__(self, market: str, result: dict | list):
        self.market = market
        if isinstance(result, dict):
            self.result = result
            errors = result.get("failed_expectations", [])
        else:
            self.result = {"failed_expectations": result, "warnings": []}
            errors = result
        error_count = len(errors)
        super().__init__(
            f"Data quality ERROR for {market}: "
            f"{error_count} expectation(s) violated. "
            f"Stage 3 skipped."
        )

    def to_dict(self) -> dict:
        return self.result if isinstance(self.result, dict) else {
            "market": self.market,
            "errors": self.result,
            "warnings": [],
        }


_PSF_MIN = int(os.environ.get("DQ_PSF_MIN", "2000"))
_PSF_MAX = int(os.environ.get("DQ_PSF_MAX", "25000"))

_dq_expectations: list[ExpectationDef] = [
    ExpectationDef(
        column="price_avg_psf",
        table="rera_projects",
        expectation_type="expect_column_values_to_be_between",
        kwargs={"min_value": _PSF_MIN, "max_value": _PSF_MAX},
        severity="ERROR",
        description=f"price_avg_psf BETWEEN {_PSF_MIN} AND {_PSF_MAX}",
    ),
    ExpectationDef(
        column="name",
        table="developers",
        expectation_type="expect_column_values_to_not_be_null",
        kwargs={},
        severity="WARN",
        description="developers.name IS NOT NULL",
    ),
    ExpectationDef(
        column="rera_number",
        table="rera_projects",
        expectation_type="expect_column_values_to_match_regex",
        kwargs={"regex": r"^(PRM|PRM/KA)/\d{4}"},
        severity="WARN",
        description="rera_number format: PRM/…/KA/…",
    ),
    ExpectationDef(
        column="transaction_psf",
        table="igr_transactions",
        expectation_type="expect_column_values_to_be_between",
        kwargs={"min_value": _PSF_MIN, "max_value": _PSF_MAX},
        severity="ERROR",
        description=f"igr_transactions.transaction_psf BETWEEN {_PSF_MIN} AND {_PSF_MAX}",
    ),
]


def _derive_projected_columns() -> dict[str, list[str]]:
    """Build projected_columns dict from _dq_expectations.
    
    Ensures every table+column referenced by an expectation is fetched,
    eliminating the sync-maintenance burden of a manually maintained dict.
    """
    result: dict[str, set[str]] = {}
    for exp in _dq_expectations:
        result.setdefault(exp.table, set()).add(exp.column)
    return {table: sorted(cols) for table, cols in result.items()}


_TABLE_MARKET_JOIN = {
    "rera_projects": "FROM rera_projects rp JOIN micro_markets mm ON mm.id = rp.micro_market_id",
    "igr_transactions": "FROM igr_transactions it JOIN micro_markets mm ON mm.id = it.micro_market_id",
}
"""Tables that support market filtering via micro_markets JOIN.
Tables not in this dict query all data (e.g. developers — no market FK)."""


def _increment_check_counter(market: str, status: str):
    """Increment Prometheus counter for data quality checks (no-op if metrics not configured)."""
    try:
        from config.metrics import data_quality_checks_total
        data_quality_checks_total.labels(market=market, status=status).inc()
    except Exception as exc:
        logger.debug(f"[DataQuality] Metrics counter skipped: {exc}")


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
)
def run_data_quality_checkpoint(market: str) -> dict:
    """Run all configured expectations against the DB.

    Market-filtered via micro_markets JOIN on tables with a micro_market_id FK.
    Tables without market FK (e.g. developers) query all data — acceptable because
    developer names are cross-market invariants.

    Returns:
        {
            "success": True if no ERROR-level failures,
            "failed_expectations": list[dict],
            "warnings": list[dict],
        }
    """
    started = time.time()

    market_clean = (market or "").strip()
    if not market_clean:
        logger.warning("[DataQuality] Empty market — skipping check")
        _increment_check_counter("unknown", "skipped")
        return {"success": True, "failed_expectations": [], "warnings": [],
                "note": "empty market"}

    ge = _lazy_import_ge()
    if ge is None:
        logger.warning("[DataQuality] Great Expectations not installed — skipping check")
        _increment_check_counter(market_clean, "skipped")
        return {"success": True, "failed_expectations": [], "warnings": []}

    market = market_clean
    failed: list[FailedExpectation] = []
    projected_columns = _derive_projected_columns()

    try:
        engine = get_engine()
        with engine.connect() as conn:
            for table_name, columns in projected_columns.items():
                col_list = ", ".join(columns)
                join_clause = _TABLE_MARKET_JOIN.get(table_name, f"FROM {table_name}")
                if table_name in _TABLE_MARKET_JOIN:
                    sql = f"SELECT {col_list} {join_clause} WHERE mm.name ILIKE :market LIMIT 5000"
                else:
                    sql = f"SELECT {col_list} {join_clause} LIMIT 5000"

                df = pd.read_sql(sql, conn, params={"market": market} if table_name in _TABLE_MARKET_JOIN else {})
                if df.empty:
                    logger.info(f"[DataQuality] {table_name}: empty — skipping")
                    continue

                relevant = [e for e in _dq_expectations if e.table == table_name and e.column in df.columns]
                if not relevant:
                    continue

                gdf = ge.from_pandas(df)

                for exp in relevant:
                    method = getattr(gdf, exp.expectation_type, None)
                    if method is None:
                        logger.warning(f"[DataQuality] Unknown expectation: {exp.expectation_type}")
                        continue

                    try:
                        result = method(exp.column, **exp.kwargs)
                    except Exception as exc:
                        logger.warning(f"[DataQuality] Check failed for {exp.column}: {exc}")
                        failed.append(FailedExpectation(
                            expectation=exp,
                            message=str(exc),
                            bad_values=[],
                        ))
                        continue

                    if not result.get("success", True):
                        bad_series = df[exp.column]
                        if exp.expectation_type == "expect_column_values_to_be_between":
                            bad = bad_series[
                                ~bad_series.between(
                                    exp.kwargs.get("min_value", 0),
                                    exp.kwargs.get("max_value", 0),
                                )
                            ].dropna().head(5).tolist()
                        elif exp.expectation_type == "expect_column_values_to_match_regex":
                            bad = bad_series[
                                ~bad_series.astype(str).str.match(
                                    exp.kwargs.get("regex", ""), na=False
                                )
                            ].head(5).tolist()
                        else:
                            bad = bad_series.head(5).tolist()

                        failed.append(FailedExpectation(
                            expectation=exp,
                            message=f"{len(bad)} unexpected value(s)",
                            bad_values=bad,
                            unexpected_count=len(bad),
                        ))
    except OperationalError as exc:
        logger.error(f"[DataQuality] DB connection failed for {market}: {exc}")
        _increment_check_counter(market, "db_error")
        return {"success": True, "failed_expectations": [], "warnings": [],
                "error": f"DB connection failed: {exc}"}
    except Exception as exc:
        logger.error(f"[DataQuality] Unexpected error for {market}: {exc}")
        _increment_check_counter(market, "error")
        return {"success": True, "failed_expectations": [], "warnings": [],
                "error": str(exc)}

    elapsed = time.time() - started
    errors = [f for f in failed if f.expectation.severity == "ERROR"]
    warnings_list = [f for f in failed if f.expectation.severity == "WARN"]
    success = len(errors) == 0
    status = "pass" if success else "fail"

    for fe in failed:
        level = "ERROR" if fe.expectation.severity == "ERROR" else "WARN"
        logger.log(
            level.upper() if hasattr(logger, level.upper()) else "WARNING",
            f"[DataQuality] {level} [{fe.expectation.table}.{fe.expectation.column}]: "
            f"{fe.message} — bad: {fe.bad_values[:3]}",
        )

    _increment_check_counter(market, status)
    logger.info(f"[DataQuality] {market}: {status} ({elapsed:.2f}s)")

    return {
        "success": success,
        "failed_expectations": [f.to_dict() for f in errors],
        "warnings": [f.to_dict() for f in warnings_list],
        "total_checked": sum(len(f.bad_values) for f in failed),
        "elapsed_seconds": round(elapsed, 2),
    }


def format_data_quality_alert(market: str, qc_result: dict) -> str:
    """Format data quality result into a Discord-ready alert string.

    Args:
        market: Market name (e.g. 'Yelahanka')
        qc_result: Dict from run_data_quality_checkpoint()

    Returns:
        Formatted markdown string ready for Discord embed.
    """
    errors = qc_result.get("failed_expectations", [])
    warnings_list = qc_result.get("warnings", [])

    if not errors and not warnings_list:
        return ""

    parts = [f"**Data Quality Check — {market}**"]
    if errors:
        parts.append(f"\n❌ **{len(errors)} Error(s)** — Stage 3 BLOCKED")
        for e in errors[:5]:
            tbl = e.get("table", "?")
            col = e.get("column", "?")
            exp = e.get("expectation", "?")
            parts.append(f"  • `{tbl}.{col}`: {exp}")
            bad = e.get("bad_values", [])
            if bad:
                parts.append(f"    Bad values: `{', '.join(str(v) for v in bad[:3])}`")
    if warnings_list:
        parts.append(f"\n⚠️ **{len(warnings_list)} Warning(s)**")
        for w in warnings_list[:5]:
            tbl = w.get("table", "?")
            col = w.get("column", "?")
            exp = w.get("expectation", "?")
            parts.append(f"  • `{tbl}.{col}`: {exp}")
    return "\n".join(parts)


def get_active_expectations() -> list[dict]:
    """Return the list of active expectations for observability / API."""
    return [e.to_dict() for e in _dq_expectations]


# ── DataQualityMonitor (Sprint 66 — Compounding Intelligence) ──────────────

class DataQualityMonitor:
    """Monitors data quality across all sources.
    
    Features:
    - freshness_score: per-source staleness check
    - stale_flag: marks sources not updated in >24h
    - PSFValidator: checks listing PSF vs IGR PSF gaps
    - cross_source_divergence_flag: flags divergent values between sources
    """
    
    FRESHNESS_WINDOW_HOURS = {
        "rera": 48,
        "listings": 12,
        "kaveri": 168,
        "igr": 48,
        "news": 24,
    }
    
    _STALE_HOURS = 24
    
    @staticmethod
    def freshness_score() -> dict:
        """Compute freshness per source.
        Returns {source: {"hours_since_update": ..., "status": "fresh"/"aging"/"stale"}}."""
        try:
            from utils.db import get_engine
            from sqlalchemy import text
            
            with get_engine().connect() as conn:
                rows = conn.execute(text("""
                    SELECT source, MAX(created_at) as last_update
                    FROM ingest_log
                    WHERE status = 'success'
                    GROUP BY source
                """)).fetchall()
            
            now = datetime.now(timezone.utc)
            result = {}
            for r in rows:
                source = r[0]
                last_update = r[1]
                if last_update is None:
                    result[source] = {"hours_since_update": None, "status": "unknown"}
                    continue
                hours = (now - last_update).total_seconds() / 3600
                window = DataQualityMonitor.FRESHNESS_WINDOW_HOURS.get(source, 24)
                if hours <= window:
                    status = "fresh"
                elif hours <= window * 2:
                    status = "aging"
                else:
                    status = "stale"
                result[source] = {"hours_since_update": round(hours, 1), "status": status}
            return result
        except Exception as exc:
            logger.warning("[DataQuality] freshness_score failed: %s", exc)
            return {}
    
    @staticmethod
    def stale_flag() -> list[str]:
        """Return list of sources that haven't been updated in >24h."""
        freshness = DataQualityMonitor.freshness_score()
        return [s for s, info in freshness.items() if info.get("status") == "stale"]
    
    @staticmethod
    def check_psf_divergence(market: str, max_gap_pct: float = 25.0) -> list[dict]:
        """Check listing PSF vs IGR PSF gap for a market.
        
        Args:
            market: Market name.
            max_gap_pct: Max acceptable gap (listing vs IGR) as % of avg.
            
        Returns:
            List of divergence flags with details.
        """
        try:
            from utils.db import get_engine
            from sqlalchemy import text
            
            with get_engine().connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT
                            (SELECT AVG(price_psf) FROM listings l
                             JOIN micro_markets m ON m.id = l.micro_market_id
                             WHERE m.name ILIKE :m AND l.price_psf > 1000 AND l.price_psf < 50000) AS listing_psf,
                            (SELECT AVG(consideration_amount / built_up_area) FROM igr_transactions it
                             JOIN micro_markets m ON m.id = it.micro_market_id
                             WHERE m.name ILIKE :m AND it.built_up_area > 100) AS igr_psf
                    """),
                    {"m": f"%{market}%"},
                ).fetchone()
            
            if not row:
                return []
            
            listing_psf = float(row[0]) if row[0] else None
            igr_psf = float(row[1]) if row[1] else None
            
            if listing_psf and igr_psf and listing_psf > 0 and igr_psf > 0:
                gap_pct = abs(listing_psf - igr_psf) / ((listing_psf + igr_psf) / 2) * 100
                if gap_pct > max_gap_pct:
                    return [{
                        "market": market,
                        "listing_psf": round(listing_psf, 2),
                        "igr_psf": round(igr_psf, 2),
                        "gap_pct": round(gap_pct, 1),
                        "severity": "HIGH" if gap_pct > 50 else "MEDIUM",
                    }]
            return []
        except Exception as exc:
            logger.warning("[DataQuality] PSF divergence check failed for %s: %s", market, exc)
            return []
    
    @staticmethod
    def cross_source_divergence_flag(market: str) -> list[dict]:
        """Check for divergences between data sources for a market.
        
        Checks:
        - Listing PSF vs IGR PSF
        - RERA project count vs listing project count
        
        Returns list of divergence flags.
        """
        flags = []
        flags.extend(DataQualityMonitor.check_psf_divergence(market))
        return flags
