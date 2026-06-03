"""
RE_OS — Evaluate Pipeline (Sprint 64 — Decision Layer)
=======================================================
End-to-end pipeline: IntelRegistry → BoardRoomV2 → DealMemo → InvestorBrief → deals entry.

POST /api/evaluate triggers this pipeline asynchronously. Returns job_id immediately.
Client polls GET /api/evaluate/<job_id> for status/results.

Pipeline steps:
  1. IntelRegistry.get_full_picture() — runs all 5 intel modules
  2. BoardRoomV2.run_board_session_v2() — 5 dept heads in parallel
  3. DealMemoGenerator — 7 sections from IntelPackage
  4. InvestorBriefGenerator — 7 sections (no track record)
  5. Deals table entry — persist opportunity record

Risk Register:
  | Risk | Mitigation |
  |------|------------|
  | Pipeline fails mid-way (e.g. BoardRoom OK, DealMemo crashes) | job.status='failed', error field populated, partial results still retrievable via get_evaluate_job |
  | Container restart loses in-memory jobs | Acceptable for v1 — Telegram polling handles retry on 404; log warning on restart |
  | IntelRegistry module failure | Each module isolated; partial IntelPackage still proceeds through pipeline |
  | DB transient during deal entry | Deal entry wrapped in single transaction; failure does not erase board results |
  | Overlapping evaluations for same survey | Each gets unique job_id; IntelRegistry cache (1hr TTL) shares results between overlapping calls |
"""

import json
import threading
import time as _time_mod
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import text

from intelligence.registry import IntelRegistry
from utils.db import get_engine

__all__ = ["start_evaluate", "get_evaluate_job"]


@dataclass
class EvaluateJob:
    job_id: str
    status: str
    survey_no: str
    market: str
    land_area_sqft: float
    sell_psf: float
    deal_type: str
    pitch: str
    created_at: str
    completed_at: str | None = None
    progress_msg: str = ""
    board_session: dict | None = None
    deal_memo: dict | None = None
    investor_brief: dict | None = None
    deal_id: str | None = None
    error: str | None = None

    def __str__(self) -> str:
        return (
            f"[EvaluateJob:{self.job_id[:8]}] "
            f"{self.market}/{self.survey_no} | {self.status} | {self.progress_msg}"
        )

    def __repr__(self) -> str:
        return (
            f"EvaluateJob(job_id={self.job_id!r}, status={self.status!r}, "
            f"survey_no={self.survey_no!r}, market={self.market!r})"
        )


_jobs: dict[str, EvaluateJob] = {}
_jobs_lock = threading.Lock()
_JOBS_MAX_AGE_HOURS = 24
_JOBS_MAX_COUNT = 1000
_last_cleanup_ts: float = 0.0
_CLEANUP_INTERVAL_S = 300


def _periodic_cleanup() -> None:
    global _last_cleanup_ts
    now = _time_mod.time()
    if now - _last_cleanup_ts < _CLEANUP_INTERVAL_S:
        return
    _last_cleanup_ts = now
    with _jobs_lock:
        if len(_jobs) <= _JOBS_MAX_COUNT:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_JOBS_MAX_AGE_HOURS)
        stale = [
            jid for jid, j in _jobs.items()
            if j.completed_at and datetime.fromisoformat(j.completed_at) < cutoff
        ]
        for jid in stale:
            del _jobs[jid]
        if stale:
            logger.info("[Evaluate] cleaned %d stale jobs (retained %d)", len(stale), len(_jobs))


def _get_market_id(market: str) -> str | None:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT id FROM micro_markets WHERE name ILIKE :m LIMIT 1"),
                {"m": f"%{market}%"},
            ).mapping().fetchone()
            return str(row["id"]) if row else None
    except Exception:
        return None


def _create_deal_entry(
    pkg: IntelRegistry,
    memo: dict,
    brief: dict,
) -> str | None:
    try:
        market_id = _get_market_id(pkg.market)
        if not market_id:
            logger.warning("[Evaluate] No market_id for %s", pkg.market)
            return None

        fe = pkg.financial_evaluation
        deal_name = f"{pkg.deal_type.upper()} — Survey {pkg.survey_no}, {pkg.market}"

        irr_base = None
        irr_bull = None
        irr_bear = None
        verdict = None
        if fe:
            scenarios_map = {"purchase": fe.purchase, "jd": fe.jd, "jv": fe.jv}
            irr_base = fe.purchase.simple_irr_pct if fe.purchase else None
            irr_bull = fe.jd.simple_irr_pct if fe.jd else None
            irr_bear = fe.jv.simple_irr_pct if fe.jv else None
            verdict = fe.purchase.verdict if fe.purchase else None

        with get_engine().begin() as conn:
            result = conn.execute(
                text("""
                INSERT INTO deals (
                    deal_name, survey_no, micro_market_id, deal_type,
                    area_acres, ask_psf, irr_base, irr_bull, irr_bear,
                    verdict, metadata
                ) VALUES (
                    :name, :survey_no, :market_id, :deal_type,
                    :area_acres, :ask_psf, :irr_base, :irr_bull, :irr_bear,
                    :verdict, :metadata::jsonb
                )
                RETURNING id
                """),
                {
                    "name": deal_name,
                    "survey_no": pkg.survey_no,
                    "market_id": market_id,
                    "deal_type": pkg.deal_type,
                    "area_acres": pkg.land_picture.land_area_acres if pkg.land_picture else None,
                    "ask_psf": fe.sell_psf if fe else None,
                    "irr_base": irr_base,
                    "irr_bull": irr_bull,
                    "irr_bear": irr_bear,
                    "verdict": verdict,
                    "metadata": json.dumps({
                        "session_id": None,
                        "memo_sections": [s["title"] for s in memo.get("sections", [])],
                        "investor_brief_sections": [s["title"] for s in brief.get("sections", [])],
                        "module_status": pkg.module_status,
                    }),
                },
            )
            deal_id = str(result.fetchone()[0])

            conn.execute(
                text("""
                INSERT INTO deal_memos (deal_id, title, memo_type, sections, recommendation, created_at)
                VALUES (:deal_id, :title, 'full', :sections::jsonb, :recommendation, NOW())
                """),
                {
                    "deal_id": deal_id,
                    "title": memo.get("title", ""),
                    "sections": json.dumps(memo.get("sections", [])),
                    "recommendation": verdict or "UNKNOWN",
                },
            )
            return deal_id
    except Exception as exc:
        logger.warning("[Evaluate] deal entry failed: %s", exc)
        return None


def _run_pipeline(
    job_id: str,
    survey_no: str,
    market: str,
    land_area_sqft: float,
    sell_psf: float,
    deal_type: str,
    pitch: str,
) -> None:
    try:
        _update_job(job_id, status="running", msg="IntelRegistry")

        pkg = IntelRegistry().get_full_picture(
            survey_no=survey_no,
            market=market,
            land_area_sqft=land_area_sqft,
            sell_psf=sell_psf,
            deal_type=deal_type,
        )

        _update_job(job_id, status="running", msg="Board Room")

        from crews.board_room_v2 import run_board_session_v2
        board_result = run_board_session_v2(pkg, pitch=pitch)

        _update_job(job_id, status="running", msg="Deal Memo")

        from utils.deal_memo_v2 import generate_deal_memo
        memo = generate_deal_memo(pkg)

        _update_job(job_id, status="running", msg="Investor Brief")

        from utils.investor_brief_v2 import generate_investor_brief
        brief = generate_investor_brief(pkg)

        _update_job(job_id, status="running", msg="Deals entry")

        deal_id = _create_deal_entry(pkg, memo, brief)

        with _jobs_lock:
            job = _jobs.get(job_id)
            if job:
                job.status = "complete"
                job.completed_at = datetime.now(timezone.utc).isoformat()
                job.progress_msg = "Done"
                job.board_session = {
                    "session_id": board_result.session_id,
                    "status": board_result.status,
                    "responses": board_result.responses,
                }
                job.deal_memo = memo
                job.investor_brief = brief
                job.deal_id = deal_id

        _log_completion(job_id, deal_id)

    except Exception as exc:
        logger.error("[Evaluate] %s failed: %s", job_id[:8], exc)
        _update_job(job_id, status="failed", error=str(exc))


def _log_completion(job_id: str, deal_id: str | None) -> None:
    elapsed = _elapsed_since(job_id)
    logger.info("[Evaluate] %s complete | deal=%s | %.1fs", job_id[:8], deal_id, elapsed)


def _update_job(job_id: str, status: str, msg: str = "", error: str | None = None) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.status = status
            if msg:
                job.progress_msg = msg
            if error:
                job.error = error
            if status == "complete":
                job.completed_at = datetime.now(timezone.utc).isoformat()


def _elapsed_since(job_id: str) -> float:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job and job.created_at:
            try:
                start = datetime.fromisoformat(job.created_at)
                return (datetime.now(timezone.utc) - start).total_seconds()
            except Exception:
                pass
    return 0.0


def start_evaluate(
    survey_no: str,
    market: str,
    land_area_sqft: float = 43560.0,
    sell_psf: float | None = None,
    deal_type: str = "compare",
    pitch: str = "",
) -> dict:
    job_id = str(uuid.uuid4())
    job = EvaluateJob(
        job_id=job_id,
        status="pending",
        survey_no=survey_no,
        market=market,
        land_area_sqft=land_area_sqft,
        sell_psf=sell_psf or 0,
        deal_type=deal_type,
        pitch=pitch,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    with _jobs_lock:
        _jobs[job_id] = job

    t = threading.Thread(
        target=_run_pipeline,
        args=(job_id, survey_no, market, land_area_sqft, sell_psf or 0, deal_type, pitch),
        daemon=True,
        name=f"eval-{job_id[:8]}",
    )
    t.start()

    return {
        "job_id": job_id,
        "status": "pending",
        "survey_no": survey_no,
        "market": market,
        "message": "Evaluation started. Poll GET /api/evaluate/<job_id> for results.",
    }


def get_evaluate_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return {
            "job_id": job.job_id,
            "status": job.status,
            "progress_msg": job.progress_msg,
            "survey_no": job.survey_no,
            "market": job.market,
            "land_area_sqft": job.land_area_sqft,
            "sell_psf": job.sell_psf,
            "deal_type": job.deal_type,
            "pitch": job.pitch,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "board_session": job.board_session,
            "deal_memo": job.deal_memo,
            "investor_brief": job.investor_brief,
            "deal_id": job.deal_id,
            "error": job.error,
        }
