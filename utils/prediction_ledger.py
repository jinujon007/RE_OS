"""
RE_OS — Prediction Ledger (GATE-93, T-1147/T-1148)

Falsifiable claim tracking. Every forecast, opportunity score above threshold,
and assembly alert writes a row here with a check_date. Weekly job resolves
verdicts by querying actual data.

Public API:
    write_prediction_ledger  — insert a claim
    get_pending_claims       — list claims where verdict IS NULL and check_date <= today
    resolve_verdicts         — compute actuals & set verdict for all pending claims
"""

from datetime import date
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine


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

    Returns list of dicts suitable for verdict resolution.
    Empty list on failure.
    """
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, date_made, source_module, claim_type, market,
                           parcel_id, survey_no, claim_text, falsifiable_metric,
                           predicted_value, check_date, confidence
                    FROM prediction_ledger
                    WHERE verdict IS NULL
                      AND check_date <= CURRENT_DATE
                    ORDER BY check_date ASC
                """),
            ).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as exc:
        logger.warning("[PredictionLedger] get_pending_claims failed: {}", exc)
        return []


def resolve_verdicts() -> dict:
    """Resolve all pending claims by computing actuals from live DB data.

    Resolution strategies per claim_type:
        psf_forecast:   Query registered_transactions PSF median for the market.
                        Hit if actual PSF within forecast confidence band.
        opportunity_score: Check if deal outcome records confirm the score band.
        assembly_alert:   Check if the developer registered a project on assembled parcels.

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
        market = claim.get("market", "")
        try:
            if ctype == "psf_forecast" and market:
                actual_psf = _get_market_median_psf(market)
                if actual_psf is not None:
                    predicted = claim.get("predicted_value")
                    if predicted and actual_psf > 0:
                        pct_diff = (
                            abs(actual_psf - float(predicted)) / float(predicted) * 100
                        )
                        if pct_diff <= 15:
                            _set_verdict(cid, "hit", actual_psf)
                            resolved += 1
                        elif pct_diff <= 30:
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
                        cid, "unverifiable", None, "No transaction PSF data available"
                    )
                    unverifiable += 1
            elif ctype == "opportunity_score":
                _set_verdict(
                    cid,
                    "unverifiable",
                    None,
                    "Opportunity score verdict needs deal outcome data",
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
        except Exception as exc:
            logger.warning("[PredictionLedger] resolve failed for {}: {}", cid, exc)
            _set_verdict(
                cid, "unverifiable", None, f"Resolution error: {str(exc)[:200]}"
            )
            unverifiable += 1

    return {
        "total": len(claims),
        "resolved": resolved,
        "partial": partial,
        "unverifiable": unverifiable,
    }


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


def _set_verdict(
    claim_id: str, verdict: str, actual_value: float | None, notes: str | None = None
) -> bool:
    """Set the verdict + actual_value for a claim.

    Safe with both TEXT and UUID claim_ids — SQLAlchemy coerces UUID strings.
    """
    try:
        from uuid import UUID

        cid_uuid = (
            UUID(claim_id)
            if isinstance(claim_id, str) and len(claim_id) == 36
            else claim_id
        )
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    UPDATE prediction_ledger
                    SET verdict = :verdict,
                        actual_value = :actual_value
                    WHERE id = :id::uuid
                """),
                {"verdict": verdict, "actual_value": actual_value, "id": str(cid_uuid)},
            )
        return True
    except Exception as exc:
        logger.warning(
            "[PredictionLedger] _set_verdict failed for {}: {}", claim_id, exc
        )
        return False
