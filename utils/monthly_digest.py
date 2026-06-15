from dataclasses import dataclass, field
from typing import Any
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine

LLM_SYNTHESIS_MAX_WORDS = 80
ABSORPTION_ACCELERATE_THRESHOLD = 5.0


@dataclass
class MonthlyDigestResult:
    market: str
    psf_mom_pct: float = 0.0
    absorption_trend: str = "flat"
    pipeline_supply_added: int = 0
    gcc_events_count: int = 0
    govt_policy_events_count: int = 0
    top_opportunities: list[dict[str, Any]] = field(default_factory=list)
    llm_synthesis: str = ""

    def __repr__(self) -> str:
        return (
            f"MonthlyDigestResult(market={self.market}, psf_mom={self.psf_mom_pct:+.2f}%, "
            f"absorption={self.absorption_trend}, pipeline={self.pipeline_supply_added}u, "
            f"gcc={self.gcc_events_count}, govt={self.govt_policy_events_count}, "
            f"opps={len(self.top_opportunities)}, synth={len(self.llm_synthesis)}c)"
        )


class MonthlyIntelDigest:
    def build(self, market: str) -> MonthlyDigestResult:
        result = MonthlyDigestResult(market=market)
        try:
            engine = get_engine()
            with engine.connect() as conn:
                self._load_psf_mom(conn, market, result)
                self._load_absorption_trend(conn, market, result)
                self._load_pipeline_supply(conn, market, result)
                self._load_gcc_events(conn, market, result)
                self._load_govt_events(conn, market, result)
                self._load_top_opportunities(conn, market, result)
        except Exception as exc:
            logger.warning(f"[MonthlyIntelDigest] Build failed for {market}: {exc}")

        result.llm_synthesis = self._generate_synthesis(market, result)
        return result

    # ── PSF MoM ──────────────────────────────────────────────────────────────

    def _load_psf_mom(self, conn, market: str, result: MonthlyDigestResult) -> None:
        try:
            row = conn.execute(
                text("""
                SELECT
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_min_psf)
                    FILTER (WHERE snapshot_date >= NOW() - INTERVAL '30 days'),
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_min_psf)
                    FILTER (WHERE snapshot_date >= NOW() - INTERVAL '60 days'
                            AND snapshot_date < NOW() - INTERVAL '30 days')
                FROM project_snapshots
                WHERE micro_market_id = (SELECT id FROM micro_markets WHERE name = :market)
            """),
                {"market": market},
            ).fetchone()
            if row:
                current_psf, prior_psf = row
                if current_psf is not None and prior_psf is not None and prior_psf != 0:
                    result.psf_mom_pct = round(
                        ((current_psf - prior_psf) / prior_psf) * 100, 2
                    )
        except Exception as exc:
            logger.warning(f"[MonthlyIntelDigest] PSF MoM failed for {market}: {exc}")

    # ── Absorption trend ─────────────────────────────────────────────────────

    def _load_absorption_trend(
        self, conn, market: str, result: MonthlyDigestResult
    ) -> None:
        try:
            row = conn.execute(
                text("""
                SELECT
                    AVG(absorption_pct) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days'),
                    AVG(absorption_pct) FILTER (WHERE created_at >= NOW() - INTERVAL '60 days'
                                                 AND created_at < NOW() - INTERVAL '30 days')
                FROM rera_projects
                WHERE micro_market_id = (SELECT id FROM micro_markets WHERE name = :market)
                  AND absorption_pct IS NOT NULL
            """),
                {"market": market},
            ).fetchone()
            if row:
                current_avg, prior_avg = row
                if current_avg is not None and prior_avg is not None and prior_avg != 0:
                    change_pct = (
                        (current_avg - prior_avg) / max(abs(prior_avg), 0.01) * 100
                    )
                    if change_pct > ABSORPTION_ACCELERATE_THRESHOLD:
                        result.absorption_trend = "accelerating"
                    elif change_pct < -ABSORPTION_ACCELERATE_THRESHOLD:
                        result.absorption_trend = "decelerating"
        except Exception as exc:
            logger.warning(
                f"[MonthlyIntelDigest] Absorption trend failed for {market}: {exc}"
            )

    # ── Pipeline supply ──────────────────────────────────────────────────────

    def _load_pipeline_supply(
        self, conn, market: str, result: MonthlyDigestResult
    ) -> None:
        try:
            result.pipeline_supply_added = (
                conn.execute(
                    text("""
                SELECT COALESCE(SUM(estimated_units), 0)
                FROM supply_pipeline
                WHERE market = :market AND created_at >= NOW() - INTERVAL '30 days'
            """),
                    {"market": market},
                ).scalar()
                or 0
            )
        except Exception as exc:
            logger.warning(
                f"[MonthlyIntelDigest] Pipeline supply failed for {market}: {exc}"
            )

    # ── GCC events ───────────────────────────────────────────────────────────

    def _load_gcc_events(self, conn, market: str, result: MonthlyDigestResult) -> None:
        try:
            result.gcc_events_count = (
                conn.execute(
                    text("""
                SELECT COUNT(*)
                FROM gcc_events
                WHERE corridor_market = :market AND event_date >= NOW() - INTERVAL '30 days'
            """),
                    {"market": market},
                ).scalar()
                or 0
            )
        except Exception as exc:
            logger.warning(
                f"[MonthlyIntelDigest] GCC events failed for {market}: {exc}"
            )

    # ── Govt policy events ───────────────────────────────────────────────────

    def _load_govt_events(self, conn, market: str, result: MonthlyDigestResult) -> None:
        try:
            result.govt_policy_events_count = (
                conn.execute(
                    text("""
                SELECT COUNT(*)
                FROM govt_policy_events
                WHERE market = :market AND published_at >= NOW() - INTERVAL '30 days'
            """),
                    {"market": market},
                ).scalar()
                or 0
            )
        except Exception as exc:
            logger.warning(
                f"[MonthlyIntelDigest] Govt events failed for {market}: {exc}"
            )

    # ── Top opportunities ────────────────────────────────────────────────────

    def _load_top_opportunities(
        self, conn, market: str, result: MonthlyDigestResult
    ) -> None:
        try:
            rows = conn.execute(
                text("""
                SELECT survey_no, micro_market, composite_score, timing_score
                FROM opportunity_scores
                WHERE micro_market = :market
                ORDER BY composite_score DESC
                LIMIT 3
            """),
                {"market": market},
            ).fetchall()
            result.top_opportunities = [
                {
                    "survey_no": r[0],
                    "market": r[1],
                    "composite_score": float(r[2]),
                    "timing_score": float(r[3]),
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning(
                f"[MonthlyIntelDigest] Top opportunities failed for {market}: {exc}"
            )

    # ── LLM synthesis ────────────────────────────────────────────────────────

    def _generate_synthesis(self, market: str, result: MonthlyDigestResult) -> str:
        try:
            from config.llm_router import get_analysis_llm

            prompt = self._build_synthesis_prompt(market, result)
            llm = get_analysis_llm()
            response = llm.generate_response(
                messages=[{"role": "user", "content": prompt}]
            )
            text = getattr(response, "content", None) or (
                response if isinstance(response, str) else ""
            )
            text = text.strip()
            words = text.split()
            if len(words) > LLM_SYNTHESIS_MAX_WORDS:
                text = " ".join(words[:LLM_SYNTHESIS_MAX_WORDS]) + "…"
            return text[:400]
        except Exception:
            return ""

    def _build_synthesis_prompt(self, market: str, result: MonthlyDigestResult) -> str:
        return (
            f"In 1-2 sentences, synthesise this Bengaluru micro-market signal for a real estate developer. "
            f"Market: {market}. PSF change: {result.psf_mom_pct}%. "
            f"Absorption: {result.absorption_trend}. "
            f"Pipeline supply added: {result.pipeline_supply_added} units. "
            f"Key signals: GCC events {result.gcc_events_count}, "
            f"govt policy events {result.govt_policy_events_count}. "
            f"Respond with a single market read, no bullet points, max {LLM_SYNTHESIS_MAX_WORDS} words."
        )
