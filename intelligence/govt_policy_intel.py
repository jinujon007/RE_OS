"""
RE_OS — Govt/Infra/Policy Intelligence Module (Sprint 75 — GATE-75)

GovtPolicyIntel.compute(market) returns a GovtPolicyResult with a
north_bengaluru_score value [0,1] that feeds demand_score_v2 as its
6th component (infra_pipeline_norm, weight 0.15).

The score captures the rolling government infrastructure pipeline and
policy momentum for North Bengaluru — a forward-looking signal that
complements the GCC pipeline score.

Architecture:
    govt_policy_events table -> GovtPolicyIntel.compute()
    -> DemandSignals.infra_pipeline_norm
    -> demand_score_v2 (6-component, Sprint 75)

Scoring:
    north_bengaluru_score: weighted average of impact_score/10 for all
    North Bengaluru events, weighted by recency.
    <30 days: weight=1.0 | 30-90 days: weight=0.7 | >90 days: weight=0.4

Cache: 4-hour TTL (via MarketCache) — govt/infra signals change slowly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from intelligence._shared import (
    MarketCache, sanitize_market, timed_intel_query, validate_market,
)

__all__ = ["GovtPolicyIntel", "GovtPolicyResult"]

_CACHE_NS = "govt_policy_intel"


@dataclass
class GovtPolicyResult:
    """Composite result from GovtPolicyIntel.compute().

    Attributes:
        north_bengaluru_score: Weighted infra/policy momentum score [0, 1].
        north_bengaluru_count: Number of North Bengaluru events contributing.
        high_opportunity_count: Count of events with signal_strength='high'.
        risk_count: Count of events with signal_strength='risk'.
        top_infra_events: Top 3 infrastructure events by impact_score.
        top_policy_events: Top 3 policy events by impact_score.
        weekly_digest: LLM-generated weekly summary string.
        computed_at: ISO-8601 timestamp.
        errors: Any error messages encountered.
    """
    north_bengaluru_score: float = 0.0
    north_bengaluru_count: int = 0
    high_opportunity_count: int = 0
    risk_count: int = 0
    top_infra_events: list[dict] = field(default_factory=list)
    top_policy_events: list[dict] = field(default_factory=list)
    weekly_digest: str = ""
    computed_at: str = ""
    errors: list[str] = field(default_factory=list)


class GovtPolicyIntel:
    """Govt/Infra/Policy intelligence module.

    Public methods:
        compute(market: str) -> GovtPolicyResult
        generate_weekly_digest(market: str) -> str
        invalidate_cache(market: str | None = None)
    """

    def __init__(self, caller: str = ""):
        self._cache = MarketCache()
        self._caller = caller or "GovtPolicyIntel"

    def compute(self, market: str = "north_bengaluru_aggregate") -> GovtPolicyResult:
        """Compute govt/infra/policy intelligence score for a market.

        Args:
            market: Target market slug or "north_bengaluru_aggregate".

        Returns:
            GovtPolicyResult with north_bengaluru_score in [0.0, 1.0].
        """
        m = sanitize_market(market) if market != "north_bengaluru_aggregate" else "north_bengaluru_aggregate"

        cached = self._cache.get(_CACHE_NS, m)
        if cached is not None:
            return cached

        result = GovtPolicyResult(
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            from utils.db import get_engine
            from sqlalchemy import text

            engine = get_engine()
            with engine.connect() as conn:
                if m == "north_bengaluru_aggregate":
                    events = self._query_north_bengaluru_events(conn)
                else:
                    events = self._query_market_events(conn, m)

            result.north_bengaluru_count = len(events)
            if events:
                result.north_bengaluru_score = self._compute_weighted_score(events)

                high_opp = [e for e in events if e.get("signal_strength") == "high"]
                risks = [e for e in events if e.get("signal_strength") == "risk"]
                result.high_opportunity_count = len(high_opp)
                result.risk_count = len(risks)

                infra = sorted(
                    [e for e in events if e.get("category") == "infrastructure"],
                    key=lambda x: x.get("impact_score", 0) or 0,
                    reverse=True,
                )[:3]
                policy = sorted(
                    [e for e in events if e.get("category") == "policy"],
                    key=lambda x: x.get("impact_score", 0) or 0,
                    reverse=True,
                )[:3]
                result.top_infra_events = infra
                result.top_policy_events = policy

                self._generate_digest(result, events)
        except Exception as exc:
            logger.warning("[GovtPolicyIntel] compute failed: {}", exc)
            result.errors.append(str(exc))

        self._cache.set(_CACHE_NS, m, result, is_positive=True)
        return result

    def generate_weekly_digest(self, market: str = "north_bengaluru_aggregate") -> str:
        """Generate and return a weekly digest string directly."""
        result = self.compute(market)
        return result.weekly_digest

    def invalidate_cache(self, market: str | None = None):
        self._cache.invalidate(_CACHE_NS, market if market else None)

    def _query_north_bengaluru_events(self, conn) -> list[dict]:
        """Query events where is_north_bengaluru=True, ordered by impact."""
        from sqlalchemy import text
        with timed_intel_query("govt_policy_nb_events"):
            rows = conn.execute(text("""
                SELECT headline, category, subcategory, investment_cr,
                       stage, impact_score, signal_strength, time_horizon,
                       actionability, summary, why_it_matters,
                       is_north_bengaluru, published_date, scraped_at
                FROM govt_policy_events
                WHERE is_north_bengaluru = TRUE
                ORDER BY impact_score DESC, scraped_at DESC
                LIMIT 50
            """)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _query_market_events(self, conn, market: str) -> list[dict]:
        """Query events for a specific market."""
        from sqlalchemy import text
        mi = validate_market(market)
        if mi is None:
            return []
        with timed_intel_query("govt_policy_market_events"):
            rows = conn.execute(text("""
                SELECT headline, category, subcategory, investment_cr,
                       stage, impact_score, signal_strength, time_horizon,
                       actionability, summary, why_it_matters,
                       is_north_bengaluru, published_date, scraped_at
                FROM govt_policy_events
                WHERE micro_markets @> ARRAY[:market]::text[]
                ORDER BY impact_score DESC, scraped_at DESC
                LIMIT 20
            """), {"market": mi["name"]}).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "headline": str(row[0]) if row[0] else "",
            "category": str(row[1]) if row[1] else "",
            "subcategory": str(row[2]) if row[2] else None,
            "investment_cr": float(row[3]) if row[3] else None,
            "stage": str(row[4]) if row[4] else None,
            "impact_score": int(row[5]) if row[5] else 0,
            "signal_strength": str(row[6]) if row[6] else "emerging",
            "time_horizon": str(row[7]) if row[7] else "medium",
            "actionability": str(row[8]) if row[8] else "monitor",
            "summary": str(row[9]) if row[9] else "",
            "why_it_matters": str(row[10]) if row[10] else "",
            "is_north_bengaluru": bool(row[11]) if row[11] else False,
            "published_date": str(row[12]) if row[12] else "",
            "scraped_at": str(row[13]) if row[13] else "",
        }

    @staticmethod
    def _compute_weighted_score(events: list[dict]) -> float:
        """Weighted average of impact_score/10 with recency weights."""
        if not events:
            return 0.0

        now = datetime.now(timezone.utc)
        total_weight = 0.0
        weighted_sum = 0.0

        for evt in events:
            impact = evt.get("impact_score", 5) or 5
            impact_norm = min(impact / 10.0, 1.0)

            pub_date = evt.get("published_date")
            days_old = 365
            if pub_date:
                try:
                    if isinstance(pub_date, str):
                        pd = datetime.strptime(pub_date[:10], "%Y-%m-%d").date()
                    else:
                        pd = pub_date
                    days_old = (now.date() - pd).days
                except (ValueError, TypeError):
                    days_old = 365

            if days_old < 30:
                recency_weight = 1.0
            elif days_old < 90:
                recency_weight = 0.7
            else:
                recency_weight = 0.4

            weighted_sum += impact_norm * recency_weight
            total_weight += recency_weight

        if total_weight <= 0:
            return 0.0
        return round(min(weighted_sum / total_weight, 1.0), 4)

    def _generate_digest(self, result: GovtPolicyResult, events: list[dict]):
        """Generate weekly digest using ANALYSIS-tier LLM."""
        try:
            from config.llm_router import get_analysis_llm

            top_events = sorted(
                events,
                key=lambda x: x.get("impact_score", 0) or 0,
                reverse=True,
            )[:5]

            event_lines = []
            for evt in top_events:
                headline = evt.get("headline", "")[:100]
                impact = evt.get("impact_score", 0)
                action = evt.get("actionability", "monitor")
                event_lines.append(f"- {headline} (impact={impact}/10, action={action})")

            events_text = "\n".join(event_lines)
            prompt = (
                "Summarise 3-5 key government/infrastructure/policy developments "
                "for North Bengaluru this week. For each: headline + one-sentence "
                "RE (real estate) impact + actionability. "
                f"North Bengaluru score: {result.north_bengaluru_score:.2f}/1.00. "
                f"Events:\n{events_text}\n\n"
                "Max 400 words."
            )
            llm = get_analysis_llm()
            response = llm.invoke([prompt])
            result.weekly_digest = response.strip()
        except Exception as exc:
            logger.debug("[GovtPolicyIntel] Weekly digest generation failed: {}", exc)
            result.weekly_digest = self._fallback_digest(result, events)

    @staticmethod
    def _fallback_digest(result: GovtPolicyResult, events: list[dict]) -> str:
        """Fallback digest when LLM unavailable."""
        high_count = result.high_opportunity_count
        risk_count = result.risk_count
        total = len(events)
        score = result.north_bengaluru_score

        return (
            f"North Bengaluru Govt/Infra Summary: Score {score:.2f}/1.00 | "
            f"{total} tracked events ({high_count} high opportunity, "
            f"{risk_count} risk). "
            f"Top categories: infrastructure ({sum(1 for e in events if e.get('category')=='infrastructure')}), "
            f"policy ({sum(1 for e in events if e.get('category')=='policy')}). "
            f"Monitor STRR, Metro Phase 3, and KIADB Aerospace Park developments."
        )
