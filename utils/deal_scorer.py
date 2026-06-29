"""
RE_OS — Live Deal Scorer (GATE-161 / T-1491)

Synthesises 5 intelligence signals into a single deal score:
  1. Assembly (25%) — parcel aggregation confidence
  2. Corridor (20%) — growth corridor proximity
  3. STRR transit (15%) — metro/STRR proximity
  4. IRR (30%) — financial feasibility
  5. Kill criteria (10%) — deed pipeline health

Usage:
    result = score_deal("Yelahanka", land_cost_cr=5.0, area_acres=1.5)
    # -> {"overall_score": 0.73, "verdict": "GO", "confidence": 0.85, ...}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from loguru import logger as _loguru_logger

logger = logging.getLogger("re_os.deal_scorer")

__all__ = ["score_deal"]

# ── Weights ──────────────────────────────────────────────────────────────────

_W_ASSEMBLY = 0.25
_W_CORRIDOR = 0.20
_W_STRR = 0.15
_W_IRR = 0.30
_W_KILL_CRITERIA = 0.10

# ── IRR thresholds ───────────────────────────────────────────────────────────

_IRR_THRESHOLDS: list[tuple[float, float, float]] = [
    (18.0, float("inf"), 1.0),
    (15.0, 18.0, 0.7),
    (12.0, 15.0, 0.4),
    (float("-inf"), 12.0, 0.1),
]

_CONFIDENCE_PENALTY_PER_FALLBACK = 0.15
_MAX_REASONING_CHARS = 500

# ── Input bounds ─────────────────────────────────────────────────────────────

_MIN_LAND_COST_CR = 0.01
_MAX_LAND_COST_CR = 1_000_000.0
_MIN_AREA_ACRES = 0.01
_MAX_AREA_ACRES = 10_000.0
_SELLABLE_RATIO = 0.65
_SQFT_PER_ACRE = 43560.0


def _validate_inputs(
    land_cost_cr: float,
    area_acres: float,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(land_cost_cr, (int, float)):
        errors.append(f"land_cost_cr must be numeric, got {type(land_cost_cr).__name__}")
    elif land_cost_cr < _MIN_LAND_COST_CR:
        errors.append(f"land_cost_cr must be >= {_MIN_LAND_COST_CR}, got {land_cost_cr}")
    elif land_cost_cr > _MAX_LAND_COST_CR:
        errors.append(f"land_cost_cr must be <= {_MAX_LAND_COST_CR}, got {land_cost_cr}")
    if not isinstance(area_acres, (int, float)):
        errors.append(f"area_acres must be numeric, got {type(area_acres).__name__}")
    elif area_acres < _MIN_AREA_ACRES:
        errors.append(f"area_acres must be >= {_MIN_AREA_ACRES}, got {area_acres}")
    elif area_acres > _MAX_AREA_ACRES:
        errors.append(f"area_acres must be <= {_MAX_AREA_ACRES}, got {area_acres}")
    return errors


def _irr_score_from_pct(irr_pct: float) -> float:
    for lo, hi, score in _IRR_THRESHOLDS:
        if lo <= irr_pct < hi:
            return score
    return 0.1


def _query_market_avg_psf(market: str) -> float | None:
    try:
        from sqlalchemy import text as _sa_text
        from utils.db import get_engine
        with get_engine().connect() as conn:
            row = conn.execute(
                _sa_text("""
                    SELECT AVG(rt.psf)
                    FROM registered_transactions rt
                    JOIN micro_markets mm
                      ON mm.name ILIKE rt.hobli
                    WHERE mm.name = :market
                      AND rt.psf BETWEEN 500 AND 50000
                      AND rt.deed_type IN ('Sale', 'Sale Deed', 'Absolute Sale',
                                           'Sale Agreement', 'Sale Agreement with Possession',
                                           'Sale Deed with Possession')
                """),
                {"market": market},
            ).fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except Exception as exc:
        logger.warning("[DealScorer] avg PSF query failed for %s: %s", market, exc)
        return None


def _compute_assembly_score(market: str) -> tuple[float, int]:
    try:
        from utils.assembly_detector import AssemblyDetector
        clusters = AssemblyDetector().detect_clusters(market)
        if not clusters:
            return 0.0, 0
        confs = [c.get("confidence_score", 0) or 0 for c in clusters]
        avg_conf = sum(confs) / len(confs)
        score = min(1.0, (avg_conf - 0.3) / 0.5 * 0.8 + 0.2)
        return max(0.0, score), len(clusters)
    except Exception as exc:
        logger.warning("[DealScorer] assembly sub-score failed: %s", exc)
        return 0.5, 0


def _compute_corridor_score(market: str) -> tuple[float, int]:
    try:
        from utils.corridor_scorer import CorridorScorer
        scores = CorridorScorer().score_all()
        if not scores:
            return 0.0, 0
        market_corridors = [s for s in scores if hasattr(s, "corridor_id")
                            and getattr(s, "corridor_id", "")[:3] == market[:3]]
        if not market_corridors:
            market_corridors = scores
        top = max(market_corridors, key=lambda s: s.composite)
        return min(1.0, top.composite / 10.0), len(market_corridors)
    except Exception as exc:
        logger.warning("[DealScorer] corridor sub-score failed: %s", exc)
        return 0.5, 0


def _compute_strr_score(market: str) -> tuple[float, str]:
    try:
        from utils.strr_overlay import STRROverlay
        overlay = STRROverlay()
        stations = overlay.stations_near(market)
        if not stations:
            logger.warning("[DealScorer] no STRR stations near %s — WEAK signal", market)
        signal_str = STRROverlay.transit_signal(stations)
        if signal_str == "STRONG":
            return 1.0, signal_str
        elif signal_str == "MODERATE":
            return 0.6, signal_str
        return 0.2, signal_str
    except Exception as exc:
        logger.warning("[DealScorer] STRR sub-score failed: %s", exc)
        return 0.5, "unknown"


def _compute_irr_score(
    market: str, land_cost_cr: float, area_acres: float,
) -> tuple[float, float | None, float | None]:
    try:
        from utils.irr_model import calc_irr
        avg_psf = _query_market_avg_psf(market)
        if not avg_psf or avg_psf <= 0:
            logger.warning("[DealScorer] avg PSF unavailable for %s — IRR fallback", market)
            return 0.5, None, None
        land_cost_abs = land_cost_cr * 1_00_00_000
        sellable_sqft = area_acres * _SQFT_PER_ACRE * _SELLABLE_RATIO
        irr_result = calc_irr(
            land_cost=land_cost_abs,
            sellable_area_sqft=sellable_sqft,
            sell_psf=avg_psf,
        )
        return _irr_score_from_pct(irr_result.simple_irr_pct), irr_result.simple_irr_pct, avg_psf
    except Exception as exc:
        logger.warning("[DealScorer] IRR sub-score failed: %s", exc)
        return 0.5, None, None


def _compute_kill_criteria_score(market: str) -> tuple[float, str]:
    try:
        from utils.deed_progress import compute_throughput_projection
        tp = compute_throughput_projection()
        verdict = tp.get("projection_verdict", "at_risk")
        if verdict == "on_track":
            return 1.0, verdict
        elif verdict == "at_risk":
            return 0.5, verdict
        return 0.2, verdict
    except Exception as exc:
        logger.warning("[DealScorer] kill_criteria sub-score failed: %s", exc)
        return 0.5, "unknown"


def _make_reasoning(signals: dict[str, float], verdict: str, score: float) -> str:
    ranked = sorted(signals.items(), key=lambda kv: kv[1], reverse=True)
    top2 = [f"{k}={v:.2f}" for k, v in ranked[:2]]
    bottom1 = ranked[-1]
    msg = (
        f"Top factors: {', '.join(top2)}. "
        f"Weakest signal: {bottom1[0]}={bottom1[1]:.2f}. "
        f"Verdict: {verdict} (score={score:.2f})."
    )
    if len(msg) > _MAX_REASONING_CHARS:
        msg = msg[:_MAX_REASONING_CHARS - 3] + "..."
    return msg


def score_deal(
    market: str,
    land_cost_cr: float,
    area_acres: float,
) -> dict[str, Any]:
    """Score a land deal across all 5 intelligence layers.

    Args:
        market: Market name (Yelahanka, Devanahalli, Hebbal).
        land_cost_cr: Land cost in crores INR (>= 0.01, <= 1,000,000).
        area_acres: Land area in acres (>= 0.01, <= 10,000).

    Returns:
        dict with overall_score (0-1), verdict (GO/CAUTIOUS/NO-GO),
        confidence (0-1), signals dict with all sub-scores, and reasoning.

    Raises:
        ValueError: If inputs are out of bounds or non-numeric.
    """
    errors = _validate_inputs(land_cost_cr, area_acres)
    if errors:
        raise ValueError("; ".join(errors))

    # Track sub-score metadata for confidence calibration
    signals: dict[str, float] = {}
    fallback_count = 0
    metadata: dict[str, Any] = {}

    # 1. Assembly
    assembly_score, n_clusters = _compute_assembly_score(market)
    signals["assembly"] = assembly_score
    metadata["assembly_clusters"] = n_clusters
    if n_clusters == 0:
        fallback_count += 0.5

    # 2. Corridor
    corridor_score, n_corridors = _compute_corridor_score(market)
    signals["corridor"] = corridor_score
    metadata["corridor_count"] = n_corridors

    # 3. STRR
    strr_score, strr_signal = _compute_strr_score(market)
    signals["strr"] = strr_score
    metadata["strr_signal"] = strr_signal

    # 4. IRR
    irr_score, irr_pct, avg_psf = _compute_irr_score(market, land_cost_cr, area_acres)
    signals["irr"] = irr_score
    metadata["irr_pct"] = irr_pct
    metadata["avg_psf"] = avg_psf
    if avg_psf is None:
        fallback_count += 0.5

    # 5. Kill criteria
    kc_score, kc_verdict = _compute_kill_criteria_score(market)
    signals["kill_criteria"] = kc_score
    metadata["kc_verdict"] = kc_verdict

    # Weighted overall
    overall = (
        _W_ASSEMBLY * signals["assembly"]
        + _W_CORRIDOR * signals["corridor"]
        + _W_STRR * signals["strr"]
        + _W_IRR * signals["irr"]
        + _W_KILL_CRITERIA * signals["kill_criteria"]
    )
    overall = max(0.0, min(1.0, overall))

    if overall >= 0.7:
        verdict = "GO"
    elif overall >= 0.5:
        verdict = "CAUTIOUS"
    else:
        verdict = "NO-GO"

    # ponytail: confidence reflects fallback count + low-score adjustment.
    # Upgrade path: weight by signal volatility (std dev) and data recency
    # (from DB timestamps) for a richer model, plus per-signal quality flags.
    confidence = max(0.1, 1.0 - fallback_count * _CONFIDENCE_PENALTY_PER_FALLBACK * 0.8)
    if overall < 0.3 and confidence > 0.7:
        confidence = 0.7

    reasoning = _make_reasoning(signals, verdict, overall)

    return {
        "overall_score": round(overall, 3),
        "verdict": verdict,
        "confidence": round(confidence, 3),
        "signals": {k: round(v, 3) for k, v in signals.items()},
        "reasoning": reasoning,
        "market": market,
        "land_cost_cr": land_cost_cr,
        "area_acres": area_acres,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "assembly_clusters": metadata.get("assembly_clusters", 0),
            "corridor_count": metadata.get("corridor_count", 0),
            "strr_signal": metadata.get("strr_signal", "unknown"),
            "irr_pct": round(metadata["irr_pct"], 2) if metadata.get("irr_pct") is not None else None,
            "avg_psf": round(metadata["avg_psf"], 0) if metadata.get("avg_psf") is not None else None,
            "kc_verdict": metadata.get("kc_verdict", "unknown"),
            "fallback_count": fallback_count,
        },
    }
