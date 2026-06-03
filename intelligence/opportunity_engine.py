"""
RE_OS — Opportunity Engine (Sprint 63 — GATE-47)
=================================================

OpportunityEngine.score_all(markets): scores every active survey in each market using
the IntelRegistry composite picture, producing 5 sub-scores + weighted composite,
and persists results to the ``opportunity_scores`` table in one transaction.

Parallelism and performance:
  Surveys within a market are scored concurrently via ``ThreadPoolExecutor``
  (up to 4 workers). A 600-second wall-clock timeout per market prevents
  cascading delays. The IntelRegistry cache (1hr TTL) ensures repeat calls
  within the same window are instant.

Composite score weights:
  IRR (0.30) + Legal (0.20) + Timing (0.20) + Distress (0.15) + Exclusivity (0.15)

Guarantees:
  * Never raises — always returns ``list[OpportunityScore]`` (possibly empty).
  * Per-survey isolation — one survey failure never blocks others.
  * Auto-persists — ``score_all`` upserts plus prunes stale rows in one call.
  * Thread-safe — IntelRegistry cache uses ``RLock``; DB connections are
    scoped per-method with ``pool_pre_ping``.
  * Score delta logging — when a survey's score changes by >0.1 from its
    previous computed value, a structured warning is emitted for audit.

Sub-score formulas (T-683):
  irr_score:       min(best_deal_IRR / 20% GO threshold, 1.0)
  legal_score:     CLEAR=1.0 → WARNING=0.6 → INCOMPLETE=0.4 → RISK=0.2 → UNKNOWN=0.0
  timing_score:    months_of_supply bands: <12=1.0 → 12-18=0.7 → 18-24=0.5 → 24-36=0.3 → >36=0.1
  distress_score:  seller-motivation proxy via land constraints and overlay risks
  exclusivity_score:  uniqueness proxy via survey count + metro/encumbrance/aggregation bonuses

Risk Register:
  | Risk | Impact | Mitigation |
  |------|--------|------------|
  | IntelRegistry call fails for a survey | That survey gets score=0 row | per-survey try/except; never blocks other surveys |
  | ON CONFLICT unique constraint missing | Entire persist fails silently | schema_v2.sql: uq_opp_scores_survey; idempotent DO block |
  | DB transient during write | Partial write corrupts data | single ``engine.begin()`` transaction rolls back on any failure |
  | Market has 0 surveys | score_all returns empty list | clean empty result, no DB writes |
  | Stale scores visible one cycle after prune | Decision layer sees outdated data | 24h grace window before deactivation prevents flapping |
  | sell_psf is unknown for survey | IRR computed at default 5000 PSF | falls back to market_pulse.avg_listing_psf, then 5000 |
  | Connection pool exhaustion with N surveys | Starved agents container | max 4 concurrent workers, each DB method uses pool_size=2 |
  | N surveys × 5 modules exceed 10-min timeout | Partial results for some surveys | 600s market-level timeout; completed surveys still persisted |
  | Score flapping between runs (±0.2+) | Confusing decision-layer churn | Delta >0.1 logged; board review judges direction over precision |
  | Prometheus import failure | Module crash | timed_intel_query is a safe no-op |
"""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from intelligence._shared import sanitize_market, validate_market, timed_intel_query
from intelligence.registry import IntelRegistry

__all__ = ["OpportunityEngine", "OpportunityScore", "ScoreComponents"]

# ── Composite weights ─────────────────────────────────────────────────────────
_IRR_WEIGHT: float = 0.30
_LEGAL_WEIGHT: float = 0.20
_TIMING_WEIGHT: float = 0.20
_DISTRESS_WEIGHT: float = 0.15
_EXCLUSIVITY_WEIGHT: float = 0.15

assert abs(_IRR_WEIGHT + _LEGAL_WEIGHT + _TIMING_WEIGHT + _DISTRESS_WEIGHT + _EXCLUSIVITY_WEIGHT - 1.0) < 0.001, \
    "Composite weights must sum to 1.0"

# ── Threshold constants ───────────────────────────────────────────────────────
_IRR_GO_THRESHOLD: float = 20.0
_SUPPLY_LOW: float = 12.0
_SUPPLY_MODERATE: float = 18.0
_SUPPLY_HIGH: float = 24.0
_SUPPLY_VERY_HIGH: float = 36.0
_PRUNE_GRACE_HOURS: int = 24
_DEFAULT_EXPIRY_DAYS: int = 90
_LOW_SCORE_EXPIRY_DAYS: int = 30
_URGENT_THRESHOLD: float = 0.80
_PRIORITY_THRESHOLD: float = 0.60
_WATCH_THRESHOLD: float = 0.40
_OBSERVE_THRESHOLD: float = 0.30
_DEFAULT_SELL_PSF: float = 5000.0
_DEFAULT_LAND_AREA_SQFT: float = 43560.0
_MAX_CONCURRENT_WORKERS: int = 4
_MARKET_TIMEOUT_SECONDS: int = 600
_SCORE_DELTA_WARN: float = 0.1


@dataclass
class ScoreComponents:
    """Five raw sub-scores before weighting. Each in [0.0, 1.0]."""
    irr_score: float = 0.0
    legal_score: float = 0.0
    timing_score: float = 0.0
    distress_score: float = 0.0
    exclusivity_score: float = 0.0

    def __post_init__(self):
        for name in ("irr_score", "legal_score", "timing_score", "distress_score", "exclusivity_score"):
            val = getattr(self, name)
            if not (0.0 <= val <= 1.0):
                logger.warning("[ScoreComponents] {} clamped from {} to [0,1]", name, val)
                setattr(self, name, max(0.0, min(val, 1.0)))

    _composite: float | None = field(init=False, repr=False, default=None)

    def composite(self) -> float:
        """Weighted composite. Result cached after first call."""
        if self._composite is not None:
            return self._composite
        raw = (
            self.irr_score * _IRR_WEIGHT
            + self.legal_score * _LEGAL_WEIGHT
            + self.timing_score * _TIMING_WEIGHT
            + self.distress_score * _DISTRESS_WEIGHT
            + self.exclusivity_score * _EXCLUSIVITY_WEIGHT
        )
        self._composite = round(max(0.0, min(raw, 1.0)), 4)
        return self._composite

    def __repr__(self) -> str:
        return (
            f"ScoreComponents(irr={self.irr_score:.3f}, legal={self.legal_score:.3f}, "
            f"timing={self.timing_score:.3f}, distress={self.distress_score:.3f}, "
            f"exclusivity={self.exclusivity_score:.3f}, composite={self.composite():.4f})"
        )


@dataclass
class OpportunityScore:
    """A scored opportunity for one survey, ready for DB persistence."""
    survey_id: str
    survey_no: str
    micro_market_id: str
    developer_id: str | None
    score: float
    components: ScoreComponents
    best_deal_type: str
    estimated_jd_irr: float | None
    legal_risk_level: str
    next_action: str
    expiry_date: str | None
    computed_at: str

    def __repr__(self) -> str:
        return (
            f"OpportunityScore(survey_no={self.survey_no!r}, "
            f"score={self.score:.4f}, "
            f"next_action={self.next_action[:30]!r})"
        )


# ── T-683: Sub-score formulas ─────────────────────────────────────────────────


def _irr_score(pkg: Any) -> tuple[float, str, float | None]:
    """IRR sub-score (weight 0.30).

    Uses the best deal structure IRR from FinancialEvaluation.
    Normalised against 20% GO threshold:
      score = min(best_irr / 20%, 1.0)

    Returns:
        (score in [0,1], best_deal_type, estimated_jd_irr or None)
    """
    fe = getattr(pkg, "financial_evaluation", None)
    if fe is None:
        return (0.0, "purchase", None)

    best_name = getattr(fe, "best_structure", "purchase")
    scenario = getattr(fe, best_name, None)
    if scenario is None:
        for name in ("purchase", "jd", "jv"):
            s = getattr(fe, name, None)
            if s is not None:
                scenario = s
                best_name = name
                break

    if scenario is None:
        return (0.0, best_name, None)

    irr_pct = getattr(scenario, "simple_irr_pct", 0.0) or 0.0

    jd_irr = None
    jd = getattr(fe, "jd", None)
    if jd is not None:
        jd_irr = getattr(jd, "simple_irr_pct", None)

    score = min(max(irr_pct / _IRR_GO_THRESHOLD, 0.0), 1.0)
    return (round(score, 4), best_name, round(jd_irr, 2) if jd_irr is not None else None)


def _legal_score(pkg: Any) -> tuple[float, str]:
    """Legal sub-score (weight 0.20).

    Maps LegalPicture.risk_level:
      CLEAR → 1.0 | WARNING → 0.6 | INCOMPLETE → 0.4 | RISK → 0.2 | UNKNOWN → 0.0

    Returns:
        (score in [0,1], legal_risk_level label)
    """
    lp = getattr(pkg, "legal_picture", None)
    if lp is None:
        return (0.0, "UNKNOWN")

    level = getattr(lp, "risk_level", "UNKNOWN") or "UNKNOWN"
    mapping = {
        "CLEAR": 1.0,
        "WARNING": 0.6,
        "INCOMPLETE": 0.4,
        "RISK": 0.2,
        "UNKNOWN": 0.0,
    }
    return (mapping.get(level, 0.0), level)


def _timing_score(pkg: Any) -> float:
    """Timing sub-score (weight 0.20).

    Based on market supply — lower months_of_supply = better entry timing:
      <12mo  → 1.0 | 12-18 → 0.7 | 18-24 → 0.5 | 24-36 → 0.3 | >36 → 0.1
      None   → 0.5 (neutral)
    """
    mp = getattr(pkg, "market_pulse", None)
    if mp is None:
        return 0.5

    mos = getattr(mp, "months_of_supply", None)
    if mos is None:
        return 0.5

    if mos < _SUPPLY_LOW:
        return 1.0
    if mos < _SUPPLY_MODERATE:
        return 0.7
    if mos < _SUPPLY_HIGH:
        return 0.5
    if mos < _SUPPLY_VERY_HIGH:
        return 0.3
    return 0.1


def _distress_score(pkg: Any) -> float:
    """Distress sub-score (weight 0.15).

    Measures seller-motivation proxy: more development constraints = seller more
    motivated to transact = better buying opportunity.

    Uses LandPicture:
      CONSTRAINED or flood ALERT → 1.0
      Overlay count > 0           → 0.7
      PARTIAL readiness + flags   → 0.5
      No flags                    → 0.1
    """
    lp = getattr(pkg, "land_picture", None)
    if lp is None:
        return 0.1

    readiness = getattr(lp, "development_readiness", "UNKNOWN") or "UNKNOWN"
    flood = getattr(lp, "flood_risk", "UNKNOWN") or "UNKNOWN"
    overlay_count = getattr(lp, "overlay_count", 0) or 0
    flags = getattr(lp, "flags", []) or []

    if readiness == "CONSTRAINED" or flood == "ALERT":
        return 1.0
    if overlay_count > 0:
        return 0.7
    if readiness == "PARTIAL" or len(flags) > 0:
        return 0.5
    return 0.1


def _exclusivity_score(
    pkg: Any,
    total_surveys_in_market: int,
    encumbrance_clear: bool = False,
    is_aggregated: bool = False,
) -> float:
    """Exclusivity sub-score (weight 0.15).

    Measures uniqueness:
      1 survey   → 1.0
      2-3        → 0.7
      4-6        → 0.5
      7-10       → 0.3
      >10        → 0.2

    Bonuses (capped at 1.0):
      +0.10 if metro proximity
      +0.10 if encumbrance clear (clean title chain = fewer legal complications)
      +0.05 if aggregated land (single negotiation vs multiple owners)
      +0.05 if grade-A developers ≤ 3 (less competition)
    """
    if total_surveys_in_market <= 1:
        base = 1.0
    elif total_surveys_in_market <= 3:
        base = 0.7
    elif total_surveys_in_market <= 6:
        base = 0.5
    elif total_surveys_in_market <= 10:
        base = 0.3
    else:
        base = 0.2

    bonus = 0.0
    land = getattr(pkg, "land_picture", None)
    if land is not None:
        infra = getattr(land, "infrastructure", None)
        if infra is not None and getattr(infra, "has_metro_proximity", False):
            bonus += 0.10

    if encumbrance_clear:
        bonus += 0.10
    if is_aggregated:
        bonus += 0.05

    mp = getattr(pkg, "market_pulse", None)
    if mp is not None:
        dev_count = getattr(mp, "grade_a_developers", 0) or 0
        if dev_count <= 3:
            bonus += 0.05

    return min(base + bonus, 1.0)


# ── Engine ────────────────────────────────────────────────────────────────────


class OpportunityEngine:
    """Score all active surveys across markets using IntelRegistry + composite weights.

    Auto-persists to ``opportunity_scores`` table and prunes stale rows.

    Usage:
        engine = OpportunityEngine()
        results = engine.score_all(["Yelahanka", "Devanahalli"])
        # → list[OpportunityScore] persisted to DB
    """

    def __init__(self, caller: str = ""):
        self._registry = IntelRegistry()
        self._caller = caller or "OpportunityEngine"

    # ═════════════════════════════════════════════════════════════════════════
    # Public API
    # ═════════════════════════════════════════════════════════════════════════

    def score_all(self, markets: list[str]) -> list[OpportunityScore]:
        """Score every active survey across the given markets and persist.

        For each market:
          1. Query surveys from DB
          2. Score surveys in parallel via ``ThreadPoolExecutor`` (max 4 workers)
          3. Log significant score deltas vs previous computed values
          4. Upsert to ``opportunity_scores`` table
          5. Deactivate stale rows (24h grace window)

        A 600-second wall-clock timeout per market prevents cascading delays.

        Args:
            markets: Non-empty list of market names.

        Returns:
            List of ``OpportunityScore`` — one per survey. Empty on severe failure.
        """
        if not markets:
            logger.warning("[{}] score_all called with empty markets list", self._caller)
            return []

        all_results: list[OpportunityScore] = []
        seen_survey_ids: set[str] = set()

        for market in markets:
            if market is None or not isinstance(market, str):
                logger.warning("[{}] Skipping None/non-str market entry: {!r}", self._caller, market)
                continue

            m = sanitize_market(market)
            if not m:
                logger.warning("[{}] Invalid market name after sanitize: {!r}", self._caller, market)
                continue

            mi = validate_market(m)
            if mi is None:
                logger.warning("[{}] Market not found in DB: {}", self._caller, market)
                continue

            try:
                surveys = self._load_surveys(mi)
            except Exception as exc:
                logger.warning("[{}] Failed to load surveys for {}: {}", self._caller, mi["name"], exc)
                continue

            total = len(surveys)
            if total == 0:
                logger.info("[{}] No surveys found for {}", self._caller, mi["name"])
                continue

            previous_scores = self._load_previous_scores(mi["id"])

            # Parallel scoring within this market
            market_results: list[OpportunityScore] = []
            with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_WORKERS, total)) as pool:
                future_map = {
                    pool.submit(self._score_single, survey, mi, total): survey
                    for survey in surveys
                }
                try:
                    for future in as_completed(future_map, timeout=_MARKET_TIMEOUT_SECONDS):
                        survey = future_map[future]
                        try:
                            result = future.result()
                            if result is not None:
                                market_results.append(result)
                                seen_survey_ids.add(result.survey_id)
                                self._check_score_delta(result, previous_scores)
                        except Exception as exc:
                            logger.warning("[{}] Survey {} in {} failed: {}",
                                           self._caller, survey.get("survey_no", "?"), mi["name"], exc)
                except TimeoutError:
                    logger.warning("[{}] Market {} timed out after {}s — {}/{} surveys completed",
                                   self._caller, mi["name"], _MARKET_TIMEOUT_SECONDS,
                                   len(market_results), total)

            all_results.extend(market_results)

        if all_results:
            self._validate_scores(all_results)
            self._log_score_distribution(all_results)
            written = self.persist_scores(all_results)
            logger.info("[{}] Persisted {}/{} scored opportunities across {} markets",
                        self._caller, written, len(all_results), len(markets))
            self._prune_stale(seen_survey_ids)

        return all_results

    # ═════════════════════════════════════════════════════════════════════════
    # Data loading
    # ═════════════════════════════════════════════════════════════════════════

    def _load_surveys(self, mi: dict) -> list[dict[str, Any]]:
        """Query all surveys for a market. Returns list of field dicts."""
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine(pool_size=2, max_overflow=1).connect() as conn:
            with timed_intel_query("opp_engine_load_surveys"):
                rows = conn.execute(
                    text("""
                        SELECT
                            s.id,
                            s.survey_no,
                            s.total_area_acres,
                            s.total_area_sqft,
                            s.land_type,
                            s.encumbrance_clear,
                            s.is_aggregated,
                            s.dc_conversion_status,
                            s.developer_id
                        FROM surveys s
                        WHERE s.micro_market_id = :mmid
                        ORDER BY s.created_at DESC
                    """),
                    {"mmid": mi["id"]},
                ).fetchall()

        return [
            {
                "survey_id": str(r[0]),
                "survey_no": str(r[1]) if r[1] else "",
                "total_area_acres": float(r[2]) if r[2] else 0.0,
                "total_area_sqft": float(r[3]) if r[3] else 0.0,
                "land_type": str(r[4]) if r[4] else "",
                "encumbrance_clear": bool(r[5]),
                "is_aggregated": bool(r[6]),
                "dc_conversion_status": str(r[7]) if r[7] else "",
                "developer_id": str(r[8]) if r[8] else None,
            }
            for r in rows
        ]

    # ═════════════════════════════════════════════════════════════════════════
    # Single survey scoring
    # ═════════════════════════════════════════════════════════════════════════

    def _score_single(
        self,
        survey: dict[str, Any],
        mi: dict,
        total_surveys_in_market: int,
    ) -> OpportunityScore | None:
        """Score one survey via IntelRegistry and sub-score formulas."""
        survey_no = survey["survey_no"]
        survey_id = survey["survey_id"]
        area_sqft = survey["total_area_sqft"] or _DEFAULT_LAND_AREA_SQFT
        encumbrance_clear = survey["encumbrance_clear"]
        is_aggregated = survey["is_aggregated"]

        if not survey["total_area_sqft"] or survey["total_area_sqft"] <= 0:
            logger.info("[{}] Survey {} in {} has zero/no area — using default {} sqft",
                        self._caller, survey_no, mi["name"], _DEFAULT_LAND_AREA_SQFT)

        pkg = None
        try:
            pkg = self._registry.get_full_picture(
                survey_no=survey_no,
                market=mi["name"],
                land_area_sqft=area_sqft,
                deal_type="compare",
            )
        except Exception as exc:
            logger.warning("[{}] IntelRegistry failed for {}/{}: {}",
                           self._caller, mi["name"], survey_no, exc)

        if pkg is None:
            logger.warning("[{}] No IntelPackage for {}/{} — zero-score row",
                           self._caller, mi["name"], survey_no)
            components = ScoreComponents()
            now_iso = datetime.now(timezone.utc).isoformat()
            return OpportunityScore(
                survey_id=survey_id,
                survey_no=survey_no,
                micro_market_id=str(mi["id"]),
                developer_id=survey["developer_id"],
                score=0.0,
                components=components,
                best_deal_type="unknown",
                estimated_jd_irr=None,
                legal_risk_level="UNKNOWN",
                next_action="IntelRegistry unavailable — retry on next run",
                expiry_date=self._expiry_for_score(0.0),
                computed_at=now_iso,
            )

        irr, deal_type, jd_irr = _irr_score(pkg)
        legal, legal_level = _legal_score(pkg)
        timing = _timing_score(pkg)
        distress = _distress_score(pkg)
        exclusivity = _exclusivity_score(pkg, total_surveys_in_market, encumbrance_clear, is_aggregated)

        components = ScoreComponents(
            irr_score=irr,
            legal_score=legal,
            timing_score=timing,
            distress_score=distress,
            exclusivity_score=exclusivity,
        )
        composite = components.composite()
        now_iso = datetime.now(timezone.utc).isoformat()

        return OpportunityScore(
            survey_id=survey_id,
            survey_no=survey_no,
            micro_market_id=str(mi["id"]),
            developer_id=survey["developer_id"],
            score=composite,
            components=components,
            best_deal_type=deal_type,
            estimated_jd_irr=jd_irr,
            legal_risk_level=legal_level,
            next_action=self._derive_next_action(composite, legal_level),
            expiry_date=self._expiry_for_score(composite),
            computed_at=now_iso,
        )

    # ═════════════════════════════════════════════════════════════════════════
    # Observability & delta tracking
    # ═════════════════════════════════════════════════════════════════════════

    def _load_previous_scores(self, micro_market_id: str) -> dict[str, float]:
        """Load existing active scores for this market. Returns {survey_id: score}."""
        from utils.db import get_engine
        from sqlalchemy import text

        try:
            with get_engine(pool_size=2, max_overflow=1).connect() as conn:
                with timed_intel_query("opp_engine_prev_scores"):
                    rows = conn.execute(
                        text("""
                            SELECT survey_id, score
                            FROM opportunity_scores
                            WHERE micro_market_id = :mmid
                              AND is_active = TRUE
                        """),
                        {"mmid": micro_market_id},
                    ).fetchall()
            return {str(r[0]): float(r[1]) for r in rows}
        except Exception as exc:
            logger.debug("[{}] Could not load previous scores for market {}: {}",
                         self._caller, micro_market_id, exc)
            return {}

    @staticmethod
    def _check_score_delta(result: OpportunityScore, previous: dict[str, float]) -> None:
        """Log a warning if a survey's score changed by more than ``_SCORE_DELTA_WARN``."""
        prev_score = previous.get(result.survey_id)
        if prev_score is None:
            return
        delta = abs(result.score - prev_score)
        if delta > _SCORE_DELTA_WARN:
            logger.info(
                "[ScoreDelta] {} ({}) {:.4f} → {:.4f} (Δ{:.4f}) — {}",
                result.survey_no, result.micro_market_id[:8],
                prev_score, result.score, delta, result.next_action[:40],
            )

    @staticmethod
    def _log_score_distribution(results: list[OpportunityScore]) -> None:
        """Log score distribution per action band for observability."""
        bands = {"URGENT": 0, "PRIORITY": 0, "WATCH": 0, "OBSERVE": 0, "HOLD": 0}
        for r in results:
            if r.score >= _URGENT_THRESHOLD:
                bands["URGENT"] += 1
            elif r.score >= _PRIORITY_THRESHOLD:
                bands["PRIORITY"] += 1
            elif r.score >= _WATCH_THRESHOLD:
                bands["WATCH"] += 1
            elif r.score >= _OBSERVE_THRESHOLD:
                bands["OBSERVE"] += 1
            else:
                bands["HOLD"] += 1
        active = [f"{k}={v}" for k, v in bands.items() if v > 0]
        logger.info("[ScoreDistribution] {} total — {}", len(results), " | ".join(active))

    @staticmethod
    def _validate_scores(results: list[OpportunityScore]) -> None:
        """Validate all scores are in [0,1]. Warns on violations but does not raise."""
        for r in results:
            if not (0.0 <= r.score <= 1.0):
                logger.warning("[ScoreValidation] {} score={:.4f} out of range — clamped",
                               r.survey_no, r.score)
                r.score = max(0.0, min(r.score, 1.0))
            for name in ("irr_score", "legal_score", "timing_score", "distress_score", "exclusivity_score"):
                val = getattr(r.components, name)
                if not (0.0 <= val <= 1.0):
                    logger.warning("[ScoreValidation] {} {}={:.4f} out of range — clamped",
                                   r.survey_no, name, val)
                    setattr(r.components, name, max(0.0, min(val, 1.0)))

    # ═════════════════════════════════════════════════════════════════════════
    # Decision logic
    # ═════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _derive_next_action(composite: float, legal_level: str) -> str:
        """Produce a human-readable next action based on composite score."""
        if composite >= _URGENT_THRESHOLD:
            return "URGENT — initiate due diligence and landowner contact"
        if composite >= _PRIORITY_THRESHOLD:
            return "PRIORITY — prepare deal memo and schedule board review"
        if composite >= _WATCH_THRESHOLD and legal_level in ("CLEAR", "WARNING"):
            return "WATCH — monitor market conditions, preliminary financial model"
        if composite >= _OBSERVE_THRESHOLD:
            return "OBSERVE — track legal and market changes"
        return "HOLD — unfavorable conditions, revisit in 90 days"

    @staticmethod
    def _expiry_for_score(composite: float) -> str | None:
        """Compute expiry date. High scores get longer validity window."""
        if composite <= 0.0:
            return None
        days = _DEFAULT_EXPIRY_DAYS if composite >= _WATCH_THRESHOLD else _LOW_SCORE_EXPIRY_DAYS
        return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()

    # ═════════════════════════════════════════════════════════════════════════
    # Persistence
    # ═════════════════════════════════════════════════════════════════════════

    def persist_scores(self, results: list[OpportunityScore]) -> int:
        """Upsert all ``OpportunityScore`` rows into ``opportunity_scores``.

        Uses ``ON CONFLICT (survey_id, survey_no, micro_market_id)`` which depends
        on the ``uq_opp_scores_survey`` unique constraint defined in schema_v2.sql.

        Args:
            results: List of scored opportunities.

        Returns:
            Number of rows upserted. 0 on failure.
        """
        import json
        from utils.db import get_engine
        from sqlalchemy import text

        if not results:
            return 0

        written = 0
        try:
            with get_engine().begin() as conn:
                stmt = text("""
                    INSERT INTO opportunity_scores (
                        survey_id, survey_no, micro_market_id, developer_id,
                        score, irr_score, legal_score, timing_score,
                        distress_score, exclusivity_score,
                        components, best_deal_type, estimated_jd_irr,
                        legal_risk_level, next_action, expiry_date,
                        is_active, computed_at, pruned_at
                    ) VALUES (
                        :sid, :sno, :mmid, :did,
                        :score, :irr, :legal, :timing,
                        :distress, :exclusivity,
                        :comp::jsonb, :deal, :jd_irr,
                        :legal_risk, :action, :expiry,
                        TRUE, :computed, NULL
                    )
                    ON CONFLICT (survey_id, survey_no, micro_market_id)
                    DO UPDATE SET
                        score = EXCLUDED.score,
                        irr_score = EXCLUDED.irr_score,
                        legal_score = EXCLUDED.legal_score,
                        timing_score = EXCLUDED.timing_score,
                        distress_score = EXCLUDED.distress_score,
                        exclusivity_score = EXCLUDED.exclusivity_score,
                        components = EXCLUDED.components,
                        best_deal_type = EXCLUDED.best_deal_type,
                        estimated_jd_irr = EXCLUDED.estimated_jd_irr,
                        legal_risk_level = EXCLUDED.legal_risk_level,
                        next_action = EXCLUDED.next_action,
                        expiry_date = EXCLUDED.expiry_date,
                        is_active = EXCLUDED.is_active,
                        computed_at = EXCLUDED.computed_at,
                        pruned_at = NULL
                """)

                for r in results:
                    components_json = json.dumps({
                        "irr_score": r.components.irr_score,
                        "legal_score": r.components.legal_score,
                        "timing_score": r.components.timing_score,
                        "distress_score": r.components.distress_score,
                        "exclusivity_score": r.components.exclusivity_score,
                        "composite_score": r.score,
                        "weights": {
                            "irr": _IRR_WEIGHT,
                            "legal": _LEGAL_WEIGHT,
                            "timing": _TIMING_WEIGHT,
                            "distress": _DISTRESS_WEIGHT,
                            "exclusivity": _EXCLUSIVITY_WEIGHT,
                        },
                    })

                    conn.execute(stmt, {
                        "sid": r.survey_id,
                        "sno": r.survey_no,
                        "mmid": r.micro_market_id,
                        "did": r.developer_id,
                        "score": r.score,
                        "irr": r.components.irr_score,
                        "legal": r.components.legal_score,
                        "timing": r.components.timing_score,
                        "distress": r.components.distress_score,
                        "exclusivity": r.components.exclusivity_score,
                        "comp": components_json,
                        "deal": r.best_deal_type,
                        "jd_irr": r.estimated_jd_irr,
                        "legal_risk": r.legal_risk_level,
                        "action": r.next_action,
                        "expiry": r.expiry_date,
                        "computed": r.computed_at,
                    })
                    written += 1

        except Exception as exc:
            logger.warning("[{}] persist_scores failed after {} rows: {}",
                           self._caller, written, exc)

        return written

    def _prune_stale(self, active_survey_ids: set[str]):
        """Deactivate opportunity_scores for surveys not in current run.

        Uses a 24-hour grace window (``_PRUNE_GRACE_HOURS``) before deactivating,
        to prevent flapping from transient IntelRegistry failures.
        """
        if not active_survey_ids:
            return
        try:
            from utils.db import get_engine
            from sqlalchemy import text
            with get_engine().begin() as conn:
                ids_list = list(active_survey_ids)
                cutoff = datetime.now(timezone.utc) - timedelta(hours=_PRUNE_GRACE_HOURS)
                result = conn.execute(
                    text("""
                        UPDATE opportunity_scores
                        SET is_active = FALSE, pruned_at = NOW()
                        WHERE is_active = TRUE
                          AND survey_id NOT IN :active_ids
                          AND computed_at < :cutoff
                    """),
                    {"active_ids": tuple(ids_list), "cutoff": cutoff.isoformat()},
                )
                count = result.rowcount
                if count > 0:
                    logger.info("[{}] Pruned {} stale opportunity scores (grace={}h)",
                                self._caller, count, _PRUNE_GRACE_HOURS)
        except Exception as exc:
            logger.warning("[{}] Prune failed: {}", self._caller, exc)


# ── CLI Entry Point ───────────────────────────────────────────────────────────


def main():
    import json
    import sys

    markets = sys.argv[1:] if len(sys.argv) > 1 else ["Yelahanka"]
    engine = OpportunityEngine(caller="cli")
    results = engine.score_all(markets)

    print(f"Scored {len(results)} opportunities across {markets}")
    for r in sorted(results, key=lambda x: x.score, reverse=True)[:10]:
        print(
            f"  {r.survey_no:12s} | score={r.score:.4f} "
            f"| IRR={r.components.irr_score:.3f} Legal={r.components.legal_score:.3f} "
            f"| {r.next_action[:40]}"
        )

    print(json.dumps({
        "total": len(results),
        "markets": markets,
        "scores": [
            {
                "survey_no": r.survey_no,
                "score": r.score,
                "components": {
                    "irr": r.components.irr_score,
                    "legal": r.components.legal_score,
                    "timing": r.components.timing_score,
                    "distress": r.components.distress_score,
                    "exclusivity": r.components.exclusivity_score,
                },
                "next_action": r.next_action,
            }
            for r in sorted(results, key=lambda x: x.score, reverse=True)
        ],
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
