"""
RE_OS — Prediction Ledger (GATE-93, T-1147/T-1148)

Falsifiable claim tracking. Every forecast, opportunity score above threshold,
and assembly alert writes a row here with a check_date. Weekly job resolves
verdicts by querying actual data.

Public API:
    write_prediction_ledger     — insert a claim
    get_pending_claims          — list claims where verdict IS NULL and check_date <= today
    resolve_verdicts            — compute actuals & set verdict for all pending claims
    compute_accuracy_summary    — per-module hit/miss/partial/unverifiable rates over N weeks
    build_weekly_digest_discord_message   — weekly summary for Discord
    build_monthly_digest_discord_message  — monthly module-level breakdown for Discord
"""

from datetime import date
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine

try:
    from config.metrics import db_query_duration_seconds
    _HAS_METRICS = True
except ImportError:
    _HAS_METRICS = False
    db_query_duration_seconds = None


def write_prediction_ledger(
    source_module: str,
    claim_type: str,
    claim_text: str,
    falsifiable_metric: str,
    check_date: date,
    market: str | None = None,
    parcel_id: str | None = None,
    survey_no: str | None = None,
    predicted_value: float | None = None,
    confidence: float | None = None,
) -> bool:
    """Insert a falsifiable claim into prediction_ledger.

    Returns True on success, False on failure (logged).
    """
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO prediction_ledger
                        (date_made, source_module, claim_type, market, parcel_id,
                         survey_no, claim_text, falsifiable_metric, predicted_value,
                         check_date, confidence)
                    VALUES
                        (:date_made, :source_module, :claim_type, :market, :parcel_id,
                         :survey_no, :claim_text, :falsifiable_metric, :predicted_value,
                         :check_date, :confidence)
                """),
                {
                    "date_made": date.today(),
                    "source_module": source_module,
                    "claim_type": claim_type,
                    "market": market,
                    "parcel_id": parcel_id,
                    "survey_no": survey_no,
                    "claim_text": claim_text[:500],
                    "falsifiable_metric": falsifiable_metric[:500],
                    "predicted_value": predicted_value,
                    "check_date": check_date,
                    "confidence": confidence,
                },
            )
        return True
    except Exception as exc:
        logger.warning("[PredictionLedger] write failed: {}", exc)
        return False


def get_pending_claims() -> list[dict]:
    """Return all claims where verdict IS NULL and check_date <= today.

    Uses FOR UPDATE SKIP LOCKED to prevent concurrent scheduler workers
    from claiming the same rows (horizontal scale safety).

    Returns list of dicts suitable for verdict resolution.
    Empty list on failure.
    """
    try:
        with get_engine().begin() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, date_made, source_module, claim_type, market,
                           parcel_id, survey_no, claim_text, falsifiable_metric,
                           predicted_value, check_date, confidence
                    FROM prediction_ledger
                    WHERE verdict IS NULL
                      AND check_date <= CURRENT_DATE
                    ORDER BY check_date ASC
                    FOR UPDATE SKIP LOCKED
                """),
            ).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as exc:
        logger.warning("[PredictionLedger] get_pending_claims failed: {}", exc)
        return []


def resolve_verdicts() -> dict:
    """Resolve all pending claims by computing actuals from live DB data.

    Resolution strategies per claim_type:
        psf_forecast:       Median PSF from registered_transactions for the market month.
                            Hit if |predicted-actual|/actual ≤ 0.10.
                            Partial if ≤ 0.20. Miss if > 0.20.
                            Unverifiable if no deed data for that month.
        opportunity_score:  Avg PSF from rera_projects for the market, fallback to listings.
                            Same threshold bands. Unverifiable if neither source has data.
        assembly_alert:     Unverifiable — requires site visit confirmation.

    Returns summary dict with counts.
    """
    claims = get_pending_claims()
    if not claims:
        return {"total": 0, "resolved": 0, "partial": 0, "unverifiable": 0}

    resolved = 0
    partial = 0
    unverifiable = 0

    for claim in claims:
        ctype = claim.get("claim_type", "")
        cid = claim.get("id")
        if not cid:
            continue
        market = str(claim.get("market", ""))
        check_date = claim.get("check_date")
        try:
            if ctype == "psf_forecast" and market:
                actual = _get_market_median_psf_for_month(market, check_date)
                if actual is not None:
                    predicted = claim.get("predicted_value")
                    if predicted and actual > 0:
                        pct_diff = abs(actual - float(predicted)) / actual * 100
                        if pct_diff <= 10:
                            _set_verdict(cid, "hit", actual)
                            resolved += 1
                        elif pct_diff <= 20:
                            _set_verdict(cid, "partial", actual)
                            partial += 1
                        else:
                            _set_verdict(cid, "miss", actual)
                            resolved += 1
                    else:
                        _set_verdict(
                            cid, "unverifiable", None, "No predicted value to compare"
                        )
                        unverifiable += 1
                else:
                    _set_verdict(
                        cid, "unverifiable", None, "No registered_transactions PSF data for that month"
                    )
                    unverifiable += 1
            elif ctype == "opportunity_score" and market:
                actual_psf = _get_market_rera_avg_psf(market)
                if actual_psf is not None:
                    predicted = claim.get("predicted_value")
                    if predicted and actual_psf > 0:
                        pct_diff = abs(actual_psf - float(predicted)) / actual_psf * 100
                        if pct_diff <= 10:
                            _set_verdict(cid, "hit", actual_psf)
                            resolved += 1
                        elif pct_diff <= 20:
                            _set_verdict(cid, "partial", actual_psf)
                            partial += 1
                        else:
                            _set_verdict(cid, "miss", actual_psf)
                            resolved += 1
                    else:
                        _set_verdict(
                            cid, "unverifiable", None, "No predicted value to compare"
                        )
                        unverifiable += 1
                else:
                    _set_verdict(
                        cid, "unverifiable", None,
                        "No rera_projects or listings PSF data available",
                    )
                    unverifiable += 1
            elif ctype == "assembly_alert":
                _set_verdict(
                    cid,
                    "unverifiable",
                    None,
                    "Assembly alert verdict needs site visit confirmation",
                )
                unverifiable += 1
            else:
                _set_verdict(
                    cid,
                    "unverifiable",
                    None,
                    f"Unknown or unresolvable claim_type: {ctype}",
                )
                unverifiable += 1
        except (ConnectionError, TimeoutError) as ce:
            logger.error("[PredictionLedger] DB connection error resolving {}: {}", cid, ce)
            _set_verdict(cid, "unverifiable", None, f"DB connection error: {str(ce)[:200]}")
            unverifiable += 1
        except ValueError as ve:
            logger.warning("[PredictionLedger] value error resolving {}: {}", cid, ve)
            _set_verdict(cid, "unverifiable", None, f"Value error: {str(ve)[:200]}")
            unverifiable += 1
        except Exception as exc:
            logger.warning("[PredictionLedger] resolve failed for {}: {}", cid, exc)
            _set_verdict(
                cid, "unverifiable", None, f"Resolution error: {str(exc)[:200]}"
            )
            unverifiable += 1

    return {
        "total": len(claims),
        "resolved": resolved + partial,
        "hit_count": resolved,
        "partial": partial,
        "unverifiable": unverifiable,
    }


def _get_market_median_psf_for_month(market: str, check_date: date | None = None) -> float | None:
    """Query monthly median PSF from registered_transactions for the check_date month."""
    if check_date is None:
        logger.warning("[PredictionLedger] _get_market_median_psf_for_month called with None check_date — falling back to today. Claim may have missing data.")
        check_date = date.today()
    if _HAS_METRICS:
        _timer = db_query_duration_seconds.labels(query_name="ledger_median_psf_for_month").time()
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rt.psf)
                    FROM registered_transactions rt
                    JOIN micro_markets mm ON mm.name ILIKE :market
                    WHERE rt.psf IS NOT NULL
                      AND rt.psf BETWEEN 500 AND 50000
                      AND rt.deed_type IN ('Sale', 'Sale Deed', 'Absolute Sale')
                      AND rt.consideration_inr >= 100000
                      AND DATE_TRUNC('month', rt.reg_date) = DATE_TRUNC('month', :check_date::date)
                """),
                {"market": f"%{market}%", "check_date": check_date.isoformat()},
            ).fetchone()
            return float(row[0]) if row and row[0] else None
    except Exception as exc:
        logger.warning("[PredictionLedger] _get_market_median_psf_for_month failed: {}", exc)
        return None


def _get_market_rera_avg_psf(market: str) -> float | None:
    """Query avg PSF from rera_projects for a market, fallback to listings (single connection)."""
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT AVG(rp.price_min_psf)
                    FROM rera_projects rp
                    JOIN micro_markets mm ON mm.id = rp.micro_market_id
                    WHERE mm.name ILIKE :market
                      AND rp.price_min_psf IS NOT NULL
                      AND rp.price_min_psf BETWEEN 500 AND 50000
                      AND rp.updated_at >= CURRENT_DATE - INTERVAL '90 days'
                """),
                {"market": f"%{market}%"},
            ).fetchone()
            avg_psf = float(row[0]) if row and row[0] else None
            if avg_psf is not None:
                return avg_psf

            row = conn.execute(
                text("""
                    SELECT AVG(l.price_psf)
                    FROM listings l
                    JOIN micro_markets mm ON mm.id = l.micro_market_id
                    WHERE mm.name ILIKE :market
                      AND l.price_psf IS NOT NULL
                      AND l.price_psf BETWEEN 500 AND 50000
                      AND l.updated_at >= CURRENT_DATE - INTERVAL '90 days'
                """),
                {"market": f"%{market}%"},
            ).fetchone()
            return float(row[0]) if row and row[0] else None
    except Exception as exc:
        logger.debug("[PredictionLedger] rera/listings query failed: {}", exc)
        return None


def build_weekly_digest_discord_message() -> str | None:
    """Build a weekly summary Discord message for prediction ledger.

    Scans claims from last 365 days only to bound query cost on large ledgers.
    Returns None if no claims exist (skip Discord send).
    """
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT COALESCE(verdict, 'pending') AS v, COUNT(*) AS cnt
                    FROM prediction_ledger
                    WHERE date_made >= CURRENT_DATE - INTERVAL '365 days'
                    GROUP BY v
                """)
            ).fetchall()
        counts = {"pending": 0, "hit": 0, "miss": 0, "partial": 0, "unverifiable": 0}
        for r in rows:
            key = str(r[0])
            if key in counts:
                counts[key] = int(r[1])

        total_claims = sum(counts.values())
        if total_claims == 0:
            return None

        lifetime_hit_rate = counts["hit"] / max(counts["hit"] + counts["miss"], 1) * 100
        msg = (
            f"\U0001f4cb Prediction Ledger (weekly): {total_claims} claims tracked. "
            f"{counts['hit']} hit, {counts['miss']} miss, "
            f"{counts['partial']} partial, {counts['unverifiable']} unverifiable, "
            f"{counts['pending']} pending. "
            f"Running hit rate: {lifetime_hit_rate:.0f}% ({counts['hit']}/{max(counts['hit'] + counts['miss'], 1)} lifetime)."
        )
        return msg
    except Exception as exc:
        logger.warning("[PredictionLedger] build_weekly_digest failed: {}", exc)
        return None


def build_monthly_digest_discord_message() -> str | None:
    """Build a monthly detailed summary with module-level breakdown.

    Returns None if no claims exist.
    """
    try:
        with get_engine().connect() as conn:
            module_rows = conn.execute(
                text("""
                    SELECT source_module, verdict, COUNT(*) AS cnt
                    FROM prediction_ledger
                    GROUP BY source_module, verdict
                    ORDER BY source_module
                """)
            ).fetchall()
        module_data: dict[str, dict[str, int]] = {}
        for r in module_rows:
            mod = str(r[0])
            v = str(r[1]) if r[1] else "pending"
            if mod not in module_data:
                module_data[mod] = {"hit": 0, "miss": 0, "partial": 0, "unverifiable": 0, "pending": 0}
            if v in module_data[mod]:
                module_data[mod][v] += int(r[2])

        if not module_data:
            return None

        lines = ["\U0001f4ca Prediction Ledger — Monthly Module Breakdown:"]
        for mod, counts in sorted(module_data.items()):
            total = sum(counts.values())
            hit_rate = counts["hit"] / max(counts["hit"] + counts["miss"], 1) * 100
            lines.append(
                f"  \u2022 {mod}: {counts['hit']}H/{counts['miss']}M/{counts['partial']}P/{counts['unverifiable']}U "
                f"(hit rate: {hit_rate:.0f}%, {total} total)"
            )
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("[PredictionLedger] build_monthly_digest failed: {}", exc)
        return None


def _get_market_median_psf(market: str) -> float | None:
    """Query the latest monthly median PSF from registered_transactions for a market."""
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY psf)
                    FROM registered_transactions rt
                    JOIN micro_markets mm ON mm.name ILIKE :market
                    WHERE rt.psf IS NOT NULL
                      AND rt.psf BETWEEN 500 AND 50000
                      AND rt.reg_date >= CURRENT_DATE - INTERVAL '180 days'
                """),
                {"market": f"%{market}%"},
            ).fetchone()
            return float(row[0]) if row and row[0] else None
    except Exception as exc:
        logger.warning("[PredictionLedger] _get_market_median_psf failed: {}", exc)
        return None


def compute_accuracy_summary(weeks: int = 12) -> dict:
    """Compute prediction accuracy rates by module over the last N weeks.

    Filter uses `date_made` as the time dimension (column exists on all rows).
    The `resolved_at` column is preferred when available (set by _set_verdict
    on migration 0068+ databases), but `date_made` is the universal fallback.

    Returns:
        {
            "window_weeks": weeks,
            "overall": {
                "hit_rate": float, "partial_rate": float,
                "miss_rate": float, "unverifiable_rate": float,
                "total_resolved": int, "total_unverifiable": int
            },
            "by_module": {
                module_name: {
                    "hit_rate": float, "partial_rate": float,
                    "miss_rate": float, "unverifiable_rate": float,
                    "total": int, "hits": int, "misses": int,
                    "partials": int, "unverifiables": int
                }
            }
        }

    Returns zeros/empty if no data (never raises).
    """
    weeks = max(weeks, 1)
    try:
        with get_engine().connect() as conn:
            # Prefer resolved_at if column exists; fall back to date_made.
            # Information_schema check is 1x per call — negligible.
            has_resolved = conn.execute(
                text("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'prediction_ledger'
                      AND column_name = 'resolved_at'
                """),
            ).fetchone() is not None
            time_col = "resolved_at" if has_resolved else "date_made"

            rows = conn.execute(
                text(f"""
                    SELECT source_module, verdict, COUNT(*) AS cnt
                    FROM prediction_ledger
                    WHERE {time_col} >= CURRENT_DATE - (:weeks * INTERVAL '1 week')
                      AND verdict IS NOT NULL
                    GROUP BY source_module, verdict
                    ORDER BY source_module
                """),
                {"weeks": weeks},
            ).fetchall()
    except Exception as exc:
        logger.warning("[compute_accuracy_summary] query failed: {}", exc)
        rows = []

    module_data: dict[str, dict[str, int]] = {}
    for r in rows:
        mod = str(r[0])
        v = str(r[1])
        if mod not in module_data:
            module_data[mod] = {"hit": 0, "miss": 0, "partial": 0, "unverifiable": 0}
        if v in module_data[mod]:
            module_data[mod][v] += int(r[2])

    total_hit = sum(m["hit"] for m in module_data.values())
    total_miss = sum(m["miss"] for m in module_data.values())
    total_partial = sum(m["partial"] for m in module_data.values())
    total_unverifiable = sum(m["unverifiable"] for m in module_data.values())
    total_resolved = total_hit + total_miss + total_partial

    def _rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator > 0 else 0.0

    overall = {
        "hit_rate": _rate(total_hit, total_resolved),
        "partial_rate": _rate(total_partial, total_resolved),
        "miss_rate": _rate(total_miss, total_resolved),
        "unverifiable_rate": _rate(total_unverifiable, total_resolved + total_unverifiable),
        "total_resolved": total_resolved,
        "total_unverifiable": total_unverifiable,
    }

    by_module = {}
    for mod, counts in sorted(module_data.items()):
        m_resolved = counts["hit"] + counts["miss"] + counts["partial"]
        by_module[mod] = {
            "hit_rate": _rate(counts["hit"], m_resolved),
            "partial_rate": _rate(counts["partial"], m_resolved),
            "miss_rate": _rate(counts["miss"], m_resolved),
            "unverifiable_rate": _rate(
                counts["unverifiable"],
                m_resolved + counts["unverifiable"],
            ),
            "total": m_resolved + counts["unverifiable"],
            "hits": counts["hit"],
            "misses": counts["miss"],
            "partials": counts["partial"],
            "unverifiables": counts["unverifiable"],
        }

    return {"window_weeks": weeks, "overall": overall, "by_module": by_module}


_VALID_VERDICTS = frozenset({"hit", "miss", "partial", "unverifiable"})


def _set_verdict(
    claim_id: str, verdict: str, actual_value: float | None, notes: str | None = None
) -> bool:
    """Set the verdict + actual_value for a claim.

    Safe with both TEXT and UUID claim_ids — SQLAlchemy coerces UUID strings.
    Validates verdict against _VALID_VERDICTS before writing.

    Args:
        claim_id: UUID string (36 chars) or raw ID.
        verdict: One of hit/miss/partial/unverifiable.
        actual_value: Resolved actual value for comparison.
        notes: Optional explanation string (truncated to 500 chars).

    Returns:
        True on success, False on failure (logged).
    """
    from uuid import UUID

    if verdict not in _VALID_VERDICTS:
        logger.error("[PredictionLedger] invalid verdict '{}' for claim {}", verdict, claim_id)
        return False

    if notes and len(notes) > 500:
        notes = notes[:500]

    try:
        cid_uuid = (
            UUID(claim_id)
            if isinstance(claim_id, str) and len(claim_id) == 36
            else claim_id
        )
        params: dict = {
            "verdict": verdict,
            "actual_value": actual_value,
            "id": str(cid_uuid),
        }
        if notes:
            params["notes"] = notes[:500]
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    UPDATE prediction_ledger
                    SET verdict = :verdict,
                        actual_value = :actual_value,
                        resolved_at = NOW()
                    WHERE id = :id::uuid
                """),
                params,
            )
        if notes:
            logger.info(
                "[PredictionLedger] verdict='{}', claim={}, notes={}",
                verdict, claim_id, notes[:200],
            )
        return True
    except Exception as exc:
        # Column resolved_at may not exist yet (pre-migration-0068). Fallback without it.
        if "resolved_at" in str(exc):
            try:
                params_fallback: dict = {"verdict": verdict, "actual_value": actual_value, "id": str(cid_uuid)}
                if notes:
                    params_fallback["notes"] = notes[:500]
                with get_engine().begin() as conn:
                    conn.execute(
                        text("""
                            UPDATE prediction_ledger
                            SET verdict = :verdict,
                                actual_value = :actual_value
                            WHERE id = :id::uuid
                        """),
                        params_fallback,
                    )
                logger.info("[PredictionLedger] verdict='{}' (no resolved_at), claim={}", verdict, claim_id)
                return True
            except Exception as fallback_exc:
                logger.warning("[PredictionLedger] _set_verdict fallback failed for {}: {}", claim_id, fallback_exc)
                return False
        logger.warning("[PredictionLedger] _set_verdict failed for {}: {}", claim_id, exc)
        return False
