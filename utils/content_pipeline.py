"""
RE_OS — Content Pipeline (Sprint 53 — PR & Brand Department)
Orchestrator: PR Head → Content Writer. Produces investor-ready content.

Caches results for 1 hour (per (market, survey_no, deal_type) key).
Logs each run to agent_runs table for audit trail.
Emits Prometheus content_generation_total counter.
"""

import time
import uuid
from datetime import datetime, timezone

from loguru import logger

from agents.pr_head_agent import PRHeadAgent, PRBrief
from agents.content_writer_agent import ContentWriterAgent, ContentPack

__all__ = ["ContentPipeline", "_content_cache_clear", "_cache_key"]

_CONTENT_CACHE: dict[str, tuple[float, dict]] = {}
_CONTENT_CACHE_TTL = 3600
_CONTENT_CACHE_MAX = 100

_DEFAULT_MARKET_PSF = {
    "Yelahanka": (7200, 6000, 12000, 4),
    "Devanahalli": (5000, 4000, 8000, 2),
    "Hebbal": (11000, 8000, 15000, 3),
}


def _cache_key(market: str, survey_no: str, deal_type: str) -> str:
    return f"{market}|{survey_no}|{deal_type}"


def _content_cache_get(key: str) -> dict | None:
    entry = _CONTENT_CACHE.get(key)
    if entry is None:
        return None
    ts, data = entry
    if time.monotonic() - ts > _CONTENT_CACHE_TTL:
        del _CONTENT_CACHE[key]
        return None
    return data


def _content_cache_put(key: str, data: dict) -> None:
    if len(_CONTENT_CACHE) >= _CONTENT_CACHE_MAX:
        oldest = min(_CONTENT_CACHE.keys(), key=lambda k: _CONTENT_CACHE[k][0])
        del _CONTENT_CACHE[oldest]
    _CONTENT_CACHE[key] = (time.monotonic(), data)


def _content_cache_clear() -> None:
    _CONTENT_CACHE.clear()


def _log_content_run(result_id: str, market: str, survey_no: str, status: str) -> None:
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs (agent_id, market, event_type, status, started_at)
                    VALUES ('content_pipeline', :m, 'content_generation', :s, NOW())
                """),
                {"m": market, "s": status},
            )
    except Exception as exc:
        logger.debug("[ContentPipeline] Failed to log run to agent_runs: %s", exc)


class ContentPipeline:
    """Orchestrates PR Head → Content Writer pipeline.

    Can optionally consume data from a completed evaluate job (via job_id)
    or run fresh via IntelRegistry. Results cached for 1 hour.
    """

    def __init__(
        self,
        pr_head: PRHeadAgent | None = None,
        content_writer: ContentWriterAgent | None = None,
    ):
        self.pr_head = pr_head or PRHeadAgent()
        self.content_writer = content_writer or ContentWriterAgent()

    def _get_financial_eval_data(self, pkg) -> tuple[float, float, float, float]:
        """Extract PSF, IRR, competitor PSF range from IntelPackage."""
        avg_psf = 0.0
        irr = 0.0
        psf_low = 0.0
        psf_high = 0.0

        fe = getattr(pkg, "financial_evaluation", None)
        if fe:
            avg_psf = float(getattr(fe, "sell_psf", 0) or 0)
            for scenario in ("purchase", "jd", "jv"):
                s = getattr(fe, scenario, None)
                if s:
                    irr_val = getattr(s, "simple_irr_pct", None)
                    if irr_val is not None:
                        irr = max(irr, float(irr_val))

        mp = getattr(pkg, "market_pulse", None)
        if mp:
            psf_low = float(getattr(mp, "price_min_psf", 0) or 0)
            psf_high = float(getattr(mp, "price_max_psf", 0) or 0)

        return avg_psf, irr, psf_low, psf_high

    def _get_key_differentiators(self, pkg) -> list[str]:
        diffs = []
        mp = getattr(pkg, "market_pulse", None)
        if mp:
            bd = getattr(mp, "key_differentiators", None)
            if bd and isinstance(bd, list):
                diffs = [str(d) for d in bd if d]
        return diffs[:5]

    def run(
        self,
        market: str,
        survey_no: str,
        deal_type: str = "compare",
        job_id: str | None = None,
    ) -> dict:
        """Run the Content Pipeline.

        Checks TTL cache before invoking LLM agents.
        Logs each run to agent_runs for audit trail.
        Emits content_generation_total Prometheus counter.

        Args:
            market: Micro-market name
            survey_no: Survey number
            deal_type: Deal type (purchase, jd, jv, compare)
            job_id: Optional completed evaluate job ID

        Returns:
            Dict with job_id, status, linkedin_post, instagram_caption,
            project_brief_sections, investor_narrative, key_differentiators,
            email_subject, generated_at
        """
        ck = _cache_key(market, survey_no, deal_type)
        cached = _content_cache_get(ck)
        if cached and not job_id:
            logger.info("[ContentPipeline] Cache hit for %s", ck)
            return cached

        result_id = str(uuid.uuid4())
        pkg = None
        avg_psf = 0.0
        irr = 0.0
        psf_low = 0.0
        psf_high = 0.0
        investor_narrative = ""
        data_source = "default"

        if job_id:
            try:
                from crews.evaluate_pipeline import get_evaluate_job

                job = get_evaluate_job(job_id)
                if job and job.get("status") == "done":
                    board_session = job.get("board_session") or {}
                    deal_memo = job.get("deal_memo") or {}
                    investor_narrative = job.get("investor_brief", {}).get(
                        "narrative", ""
                    ) or str(job.get("investor_brief", "") or "")
                    avg_psf = float(
                        board_session.get("avg_psf", deal_memo.get("avg_psf", 0)) or 0
                    )
                    irr = float(board_session.get("irr", deal_memo.get("irr", 0)) or 0)
                    data_source = "evaluate_job"
                    logger.info(
                        "[ContentPipeline] Loaded data from job %s: PSF=%.0f, IRR=%.1f",
                        job_id,
                        avg_psf,
                        irr,
                    )
            except Exception as exc:
                logger.warning(
                    "[ContentPipeline] Failed to load job %s: %s — falling back to IntelRegistry",
                    job_id,
                    exc,
                )

        if avg_psf == 0.0 or pkg is None:
            try:
                from intelligence.registry import IntelRegistry

                reg = IntelRegistry()
                pkg = reg.get_full_picture(
                    survey_no=survey_no,
                    market=market,
                    deal_type=deal_type,
                )
                fetched = self._get_financial_eval_data(pkg)
                avg_psf, irr, psf_low, psf_high = fetched
                if avg_psf == 0.0 and market in _DEFAULT_MARKET_PSF:
                    defaults = _DEFAULT_MARKET_PSF[market]
                    avg_psf = float(defaults[0])
                    psf_low = float(defaults[1])
                    psf_high = float(defaults[2])
                    irr = 14.0
                    logger.info(
                        "[ContentPipeline] Using market defaults for %s: PSF=%.0f",
                        market,
                        avg_psf,
                    )
                if data_source == "default":
                    data_source = "intel_registry"
                logger.info(
                    "[ContentPipeline] IntelRegistry data: PSF=%.0f, IRR=%.1f",
                    avg_psf,
                    irr,
                )
            except Exception as exc:
                logger.warning(
                    "[ContentPipeline] IntelRegistry failed: %s — using defaults", exc
                )
                if market in _DEFAULT_MARKET_PSF:
                    defaults = _DEFAULT_MARKET_PSF[market]
                    avg_psf = float(defaults[0])
                    psf_low = float(defaults[1])
                    psf_high = float(defaults[2])
                    irr = 14.0
                    data_source = "market_defaults"

        if not investor_narrative and pkg:
            mp = getattr(pkg, "market_pulse", None)
            if mp:
                investor_narrative = str(getattr(mp, "summary", "") or "")

        diffs = self._get_key_differentiators(pkg) if pkg else []
        gac = _DEFAULT_MARKET_PSF.get(market, (0, 0, 0, 0))[3]
        input_data = {
            "market": market,
            "survey_no": survey_no,
            "deal_type": deal_type,
            "avg_psf": avg_psf,
            "psf_range_low": psf_low,
            "psf_range_high": psf_high,
            "competitor_grade_a_count": gac,
            "key_differentiators": diffs,
        }
        brief: PRBrief = self.pr_head.run(input_data)

        content_pack: ContentPack = self.content_writer.run(
            brief=brief,
            psf=avg_psf,
            irr=irr,
            market=market,
        )

        result = {
            "job_id": result_id,
            "status": "done",
            "linkedin_post": content_pack.linkedin_post,
            "instagram_caption": content_pack.instagram_caption,
            "project_brief_sections": content_pack.project_brief_sections,
            "investor_narrative": brief.investor_narrative,
            "key_differentiators": brief.key_differentiators,
            "email_subject": content_pack.email_subject,
            "project_tagline": brief.project_tagline,
            "target_segment": brief.target_segment,
            "risk_acknowledgements": brief.risk_acknowledgements,
            "data_source": data_source,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        _content_cache_put(ck, result)
        _log_content_run(result_id, market, survey_no, "success")

        try:
            from config.metrics import content_generation_total

            content_generation_total.labels(market=market, status="success").inc()
        except Exception:
            pass

        logger.info(
            "[ContentPipeline] Complete: %s/%s — LinkedIn %d chars, %d sections (source=%s, cache=%s)",
            market,
            survey_no,
            len(content_pack.linkedin_post),
            len(content_pack.project_brief_sections),
            data_source,
            "yes" if cached else "no",
        )

        return result
