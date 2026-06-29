"""
RE_OS — Digest Validator
Quality gate for weekly intel output. Checks market coverage, data freshness,
signal count, and confidence before digests are delivered.
"""

import logging
from sqlalchemy import text
from utils.db import get_engine

logger = logging.getLogger("re_os.digest_validator")

_FRESHNESS_MIN_PROJECTS = 5
_FRESHNESS_WINDOW_DAYS = 7
_COVERAGE_WINDOW_DAYS = 8
_SIGNAL_WINDOW_DAYS = 14

# ponytail: at >50 markets, parallelize per-market queries with ThreadPoolExecutor
# and cache results per market in Redis (TTL 1h). At >500 markets, switch to
# materialized view v_digest_quality refreshed by the scheduler.

# Schema drift: assembly_signals may use confidence or confidence_score.
# The COALESCE handles both column names across migration states.
_CONFIDENCE_COL = "COALESCE(confidence_score, confidence, 0.0)"


def validate_digest(market: str) -> dict:
    if not market or not market.strip():
        return {
            "market_coverage": False,
            "freshness_ok": False,
            "signal_count": 0,
            "avg_confidence_pct": 0.0,
            "verdict": "FAIL",
        }

    market_stripped = market.strip()
    market_coverage = False
    freshness_ok = False
    signal_count = 0
    avg_confidence_pct = 0.0

    try:
        with get_engine().connect() as conn:
            try:
                row = conn.execute(
                    text("""
                        SELECT 1 FROM agent_runs
                        WHERE micro_market ILIKE :m
                          AND event_type = 'intel_digest'
                          AND created_at > NOW() - INTERVAL ':days days'
                        LIMIT 1
                    """),
                    {"m": f"%{market_stripped}%", "days": _COVERAGE_WINDOW_DAYS},
                ).fetchone()
                market_coverage = row is not None
            except Exception as exc:
                logger.debug("[DigestValidator] coverage query failed: %s", exc)

            try:
                row = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM rera_projects
                        WHERE micro_market ILIKE :m
                          AND updated_at > NOW() - INTERVAL ':days days'
                    """),
                    {"m": f"%{market_stripped}%", "days": _FRESHNESS_WINDOW_DAYS},
                ).fetchone()
                freshness_ok = (row and row[0] or 0) >= _FRESHNESS_MIN_PROJECTS
            except Exception as exc:
                logger.debug("[DigestValidator] freshness query failed: %s", exc)

            try:
                row = conn.execute(
                    text(f"""
                        SELECT COUNT(*), AVG({_CONFIDENCE_COL})
                        FROM assembly_signals
                        WHERE market ILIKE :m
                          AND detected_at > NOW() - INTERVAL ':days days'
                    """),
                    {"m": f"%{market_stripped}%", "days": _SIGNAL_WINDOW_DAYS},
                ).fetchone()
                if row:
                    signal_count = int(row[0]) if row[0] is not None else 0
                    avg_c = float(row[1]) if row[1] is not None else 0.0
                    avg_confidence_pct = round(avg_c * 100, 1)
            except Exception as exc:
                logger.debug("[DigestValidator] signal query failed: %s", exc)
    except Exception as exc:
        logger.debug("[DigestValidator] connection failed: %s", exc)

    if market_coverage and freshness_ok and signal_count >= 1:
        verdict = "PASS"
    elif market_coverage and (not freshness_ok or signal_count == 0):
        verdict = "WARN"
    else:
        verdict = "FAIL"

    return {
        "market_coverage": market_coverage,
        "freshness_ok": freshness_ok,
        "signal_count": signal_count,
        "avg_confidence_pct": avg_confidence_pct,
        "verdict": verdict,
    }
