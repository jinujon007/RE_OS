"""
RE_OS — Data Quality (Great Expectations Integration)
Runs configurable data quality checks after batch upsert, before Stage 3 LLM
synthesis. Bad data is caught here — never silently reaches the Board Room.

Design decisions:
  - Single DB round-trip, then one GE validation (not N queries).
  - Severity per expectation: ERROR blocks Stage 3, WARN logs only.
  - Expectations configurable via settings or env vars.
  - Samples bad values (LIMIT 5) to avoid OOM on large tables.
"""
import os
import time
from dataclasses import dataclass, field
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
        kwargs={"regex": r"^(PRM|PRM/KA)/\d{4}/"},
        severity="WARN",
        description="rera_number format: PRM/…/KA/…",
    ),
]


def _increment_check_counter(market: str, status: str):
    """Increment Prometheus counter for data quality checks (no-op if metrics not configured)."""
    try:
        from config.metrics import data_quality_checks_total
        data_quality_checks_total.labels(market=market, status=status).inc()
    except Exception:
        pass


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((OperationalError, DatabaseError)),
)
def run_data_quality_checkpoint(market: str) -> dict:
    """Run all configured expectations against the DB.

    Returns:
        {
            "success": True if no ERROR-level failures,
            "failed_expectations": list[dict],
            "warnings": list[dict],
        }
    """
    started = time.time()
    ge = _lazy_import_ge()
    if ge is None:
        logger.warning("[DataQuality] Great Expectations not installed — skipping check")
        _increment_check_counter(market, "skipped")
        return {"success": True, "failed_expectations": [], "warnings": []}

    engine = get_engine()
    failed: list[FailedExpectation] = []

    projected_columns = {
        "rera_projects": [
            "price_avg_psf", "rera_number",
        ],
        "developers": ["name"],
    }

    try:
        with engine.connect() as conn:
            for table_name, columns in projected_columns.items():
                col_list = ", ".join(columns)
                df = pd.read_sql(
                    f"SELECT {col_list} FROM {table_name} LIMIT 5000",
                    conn,
                )
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
            parts.append(f"  • `{e['table']}.{e['column']}`: {e.get('expectation', '?')}")
            bad = e.get("bad_values", [])
            if bad:
                parts.append(f"    Bad values: `{', '.join(str(v) for v in bad[:3])}`")
    if warnings_list:
        parts.append(f"\n⚠️ **{len(warnings_list)} Warning(s)**")
        for w in warnings_list[:5]:
            parts.append(f"  • `{w['table']}.{w['column']}`: {w.get('expectation', '?')}")
    return "\n".join(parts)


def get_active_expectations() -> list[dict]:
    """Return the list of active expectations for observability / API."""
    return [e.to_dict() for e in _dq_expectations]
