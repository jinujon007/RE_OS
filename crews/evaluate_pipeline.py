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
  5. ShareholderRound — 4 agents in ThreadPoolExecutor (60s/agent), GO/NO-GO/CONDITIONAL/ABSTAIN verdicts
  6. Deals table entry — persist opportunity record

Persistence:
  Jobs are written to the evaluate_jobs table (migration 0035) at creation, on every
  progress update, and at completion/failure.  The in-memory _jobs dict is a session
  cache for fast polling during a run; on cache-miss get_evaluate_job() falls back to
  the DB so results survive container restarts.

Risk Register:
  | Risk | Mitigation |
  |------|------------|
  | Pipeline fails mid-way (e.g. BoardRoom OK, DealMemo crashes) | job.status='failed', error field populated, partial results still retrievable via get_evaluate_job |
  | Container restart loses in-memory jobs | DB fallback in get_evaluate_job() recovers completed/failed records |
  | IntelRegistry module failure | Each module isolated; partial IntelPackage still proceeds through pipeline |
  | DB transient during deal entry | Deal entry wrapped in single transaction; failure does not erase board results |
  | Overlapping evaluations for same survey | Each gets unique job_id; IntelRegistry cache (1hr TTL) shares results between overlapping calls |
"""

import json
import threading
import time as _time_mod
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import text

from intelligence.registry import IntelRegistry, IntelPackage
from utils.db import get_engine

__all__ = ["start_evaluate", "get_evaluate_job", "run_shareholder_round"]


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
    shareholder_round: list[dict] | None = None
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

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress_msg": self.progress_msg,
            "survey_no": self.survey_no,
            "market": self.market,
            "land_area_sqft": self.land_area_sqft,
            "sell_psf": self.sell_psf,
            "deal_type": self.deal_type,
            "pitch": self.pitch,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "board_session": self.board_session,
            "deal_memo": self.deal_memo,
            "investor_brief": self.investor_brief,
            "shareholder_round": self.shareholder_round,
            "deal_id": self.deal_id,
            "error": self.error,
        }


_jobs: dict[str, EvaluateJob] = {}
_jobs_lock = threading.Lock()
_JOBS_MAX_AGE_HOURS = 24
_JOBS_MAX_COUNT = 1000
_last_cleanup_ts: float = 0.0
_CLEANUP_INTERVAL_S = 300


# ── DB persistence helpers ────────────────────────────────────────────────────


def _db_insert_job(job: EvaluateJob) -> None:
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                INSERT INTO evaluate_jobs (
                    job_id, status, survey_no, market, land_area_sqft, sell_psf,
                    deal_type, pitch, created_at, progress_msg
                ) VALUES (
                    :job_id, :status, :survey_no, :market, :land_area_sqft, :sell_psf,
                    :deal_type, :pitch, :created_at, :progress_msg
                )
                ON CONFLICT (job_id) DO NOTHING
                """),
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "survey_no": job.survey_no,
                    "market": job.market,
                    "land_area_sqft": job.land_area_sqft,
                    "sell_psf": job.sell_psf,
                    "deal_type": job.deal_type,
                    "pitch": job.pitch,
                    "created_at": job.created_at,
                    "progress_msg": job.progress_msg,
                },
            )
    except Exception as exc:
        logger.warning(
            "[Evaluate] DB insert failed for job {}: {}", job.job_id[:8], exc
        )


def _db_update_job(job: EvaluateJob) -> None:
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                UPDATE evaluate_jobs SET
                    status          = :status,
                    progress_msg    = :progress_msg,
                    completed_at    = :completed_at,
                    board_session   = CAST(:board_session AS jsonb),
                    deal_memo       = CAST(:deal_memo AS jsonb),
                    investor_brief  = CAST(:investor_brief AS jsonb),
                    shareholder_round = CAST(:shareholder_round AS jsonb),
                    deal_id         = :deal_id,
                    error           = :error
                WHERE job_id = :job_id
                """),
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "progress_msg": job.progress_msg,
                    "completed_at": job.completed_at,
                    "board_session": json.dumps(job.board_session)
                    if job.board_session is not None
                    else None,
                    "deal_memo": json.dumps(job.deal_memo)
                    if job.deal_memo is not None
                    else None,
                    "investor_brief": json.dumps(job.investor_brief)
                    if job.investor_brief is not None
                    else None,
                    "shareholder_round": json.dumps(job.shareholder_round)
                    if job.shareholder_round is not None
                    else None,
                    "deal_id": job.deal_id,
                    "error": job.error,
                },
            )
    except Exception as exc:
        logger.warning(
            "[Evaluate] DB update failed for job {}: {}", job.job_id[:8], exc
        )


def _db_fetch_job(job_id: str) -> dict | None:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT * FROM evaluate_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            ).fetchone()
            if not row:
                return None
            return {
                "job_id": str(row.job_id),
                "status": row.status,
                "progress_msg": row.progress_msg or "",
                "survey_no": row.survey_no,
                "market": row.market,
                "land_area_sqft": float(row.land_area_sqft),
                "sell_psf": float(row.sell_psf),
                "deal_type": row.deal_type,
                "pitch": row.pitch or "",
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "completed_at": row.completed_at.isoformat()
                if row.completed_at
                else None,
                "board_session": row.board_session,
                "deal_memo": row.deal_memo,
                "investor_brief": row.investor_brief,
                "shareholder_round": row.shareholder_round,
                "deal_id": str(row.deal_id) if row.deal_id else None,
                "error": row.error,
            }
    except Exception as exc:
        logger.warning("[Evaluate] DB fetch failed for job {}: {}", job_id[:8], exc)
        return None


# ── In-memory helpers ─────────────────────────────────────────────────────────


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
            jid
            for jid, j in _jobs.items()
            if j.completed_at and datetime.fromisoformat(j.completed_at) < cutoff
        ]
        for jid in stale:
            del _jobs[jid]
        if stale:
            logger.info(
                "[Evaluate] cleaned {} stale jobs from cache (retained {})",
                len(stale),
                len(_jobs),
            )


def _get_market_id(market: str) -> str | None:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT id FROM micro_markets WHERE name ILIKE :m LIMIT 1"),
                {"m": f"%{market}%"},
            ).fetchone()
            return str(row[0]) if row else None
    except Exception as exc:
        logger.warning("[Evaluate] DB lookup failed for market '{}': {}", market, exc)
        return None


def _create_deal_entry(
    pkg: IntelPackage,
    memo: dict,
    brief: dict,
) -> str | None:
    try:
        market_id = _get_market_id(pkg.market)
        if not market_id:
            logger.warning("[Evaluate] No market_id for {}", pkg.market)
            return None

        fe = pkg.financial_evaluation
        deal_name = f"{pkg.deal_type.upper()} — Survey {pkg.survey_no}, {pkg.market}"

        irr_base = None
        irr_bull = None
        irr_bear = None
        verdict = None
        if fe:
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
                    :verdict, CAST(:metadata AS jsonb)
                )
                RETURNING id
                """),
                {
                    "name": deal_name,
                    "survey_no": pkg.survey_no,
                    "market_id": market_id,
                    "deal_type": pkg.deal_type,
                    "area_acres": pkg.land_picture.land_area_acres
                    if pkg.land_picture
                    else None,
                    "ask_psf": fe.sell_psf if fe else None,
                    "irr_base": irr_base,
                    "irr_bull": irr_bull,
                    "irr_bear": irr_bear,
                    "verdict": verdict,
                    "metadata": json.dumps(
                        {
                            "session_id": None,
                            "memo_sections": [
                                s["title"] for s in memo.get("sections", [])
                            ],
                            "investor_brief_sections": [
                                s["title"] for s in brief.get("sections", [])
                            ],
                            "module_status": pkg.module_status,
                        }
                    ),
                },
            )
            deal_id = str(result.fetchone()[0])

            conn.execute(
                text("""
                INSERT INTO deal_memos (deal_id, title, memo_type, sections, recommendation, created_at)
                VALUES (:deal_id, :title, 'full', CAST(:sections AS jsonb), :recommendation, NOW())
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
        logger.warning("[Evaluate] deal entry failed: {}", exc)
        return None


def run_shareholder_round(pkg: IntelPackage, deal_summary: str = "") -> list[dict]:
    """Run all 4 shareholder agents in parallel. 60s timeout per agent.

    Each shareholder returns: name, verdict (GO|NO-GO|CONDITIONAL|ABSTAIN),
    key_question, response.
    """
    try:
        from agents.shareholder_agent import build_all_shareholders

        shareholders = build_all_shareholders()
        if not shareholders:
            return [
                {
                    "name": "No Shareholders",
                    "verdict": "ABSTAIN",
                    "key_question": "N/A",
                    "response": "J-2 not complete",
                }
            ]

        context = (
            f"Market: {pkg.market}\n"
            f"Survey: {pkg.survey_no}\n"
            f"Deal type: {pkg.deal_type}\n"
            f"PSF source: {getattr(pkg.financial_evaluation, 'psf_source_quality', 'unknown')}\n"
            f"Deal summary: {deal_summary[:300] if deal_summary else 'N/A'}"
        )

        import re as _re
        import json as _json

        results = []
        executor = ThreadPoolExecutor(max_workers=4)
        try:
            future_map = {}
            for spec, agent in shareholders:
                prompt = (
                    f"You are {spec.get('name', 'a shareholder')}.\n"
                    f"Role: {spec.get('role', 'Investor')}\n"
                    f"Investment thesis: {spec.get('investment_thesis', 'Growth')}\n"
                    f"Your signature question: {spec.get('signature_question', 'Is this a good investment?')}\n\n"
                    f"Context:\n{context}\n\n"
                    f"Respond with EXACTLY this JSON format (no markdown, no extra text):\n"
                    f'{{"verdict": "GO|NO-GO|CONDITIONAL", '
                    f'"key_question": "your 1 question here", '
                    f'"response": "your rationale (max 200 chars)"}}'
                )
                future = executor.submit(agent.execute, prompt)
                future_map[future] = spec

            for future in as_completed(future_map, timeout=90):
                spec = future_map[future]
                name = spec.get("name", "Shareholder")
                try:
                    raw = future.result(timeout=60)
                    json_match = _re.search(
                        r"(?:```)?(?:json)?\s*(\{.*?\})\s*(?:```)?",
                        raw.strip(),
                        _re.DOTALL,
                    )
                    if not json_match:
                        raise ValueError(
                            "No JSON found in response: {}".format(raw[:200])
                        )
                    parsed = _json.loads(json_match.group(1))
                    verdict = parsed.get("verdict", "CONDITIONAL")
                    if verdict not in ("GO", "NO-GO", "CONDITIONAL"):
                        verdict = "CONDITIONAL"
                    results.append(
                        {
                            "name": name,
                            "verdict": verdict,
                            "key_question": parsed.get("key_question", "")[:200],
                            "response": parsed.get("response", "")[:200],
                        }
                    )
                except Exception as exc:
                    logger.warning(
                        "[ShareholderRound] {} failed/timeout: {}", name, exc
                    )
                    results.append(
                        {
                            "name": name,
                            "verdict": "ABSTAIN",
                            "key_question": "",
                            "response": "Unable to respond",
                            "error": "timeout"
                            if any(
                                w in str(exc).lower() for w in ["timeout", "timed out"]
                            )
                            else str(exc)[:100],
                        }
                    )
        except TimeoutError:
            # Overall 90s wall-clock exceeded — mark all pending futures as ABSTAIN
            pending = {future_map[f] for f in future_map if not f.done()}
            for spec in pending:
                results.append(
                    {
                        "name": spec.get("name", "Shareholder"),
                        "verdict": "ABSTAIN",
                        "key_question": "",
                        "response": "Unable to respond",
                        "error": "timeout",
                    }
                )
        finally:
            # Do NOT wait for dangling LLM threads — they have no internal timeout.
            executor.shutdown(wait=False, cancel_futures=True)
        return results
    except Exception as exc:
        logger.warning("[ShareholderRound] round failed: {}", exc)
        return []


def _run_pipeline(
    job_id: str,
    survey_no: str,
    market: str,
    land_area_sqft: float,
    sell_psf: float,
    deal_type: str,
    pitch: str,
) -> None:
    ctx = f"{market}/{survey_no}"
    t0 = _time_mod.time()
    try:
        _update_job(job_id, status="running", msg="IntelRegistry")
        pkg = IntelRegistry().get_full_picture(
            survey_no=survey_no,
            market=market,
            land_area_sqft=land_area_sqft,
            sell_psf=sell_psf,
            deal_type=deal_type,
        )
        logger.info(
            "[Evaluate] {} | IntelRegistry {:.1f}s | all_modules={}",
            ctx,
            _time_mod.time() - t0,
            pkg.all_modules_success,
        )

        _update_job(job_id, status="running", msg="Board Room")
        t1 = _time_mod.time()
        from crews.board_room_v2 import run_board_session_v2

        board_result = run_board_session_v2(pkg, pitch=pitch)
        dept_count = len(board_result.responses)
        logger.info(
            "[Evaluate] {} | BoardRoom {:.1f}s | {} depts",
            ctx,
            _time_mod.time() - t1,
            dept_count,
        )

        _update_job(job_id, status="running", msg="Deal Memo")
        from utils.deal_memo_v2 import generate_deal_memo

        memo = generate_deal_memo(pkg)
        memo_section_count = len(memo.get("sections", []))

        _update_job(job_id, status="running", msg="Investor Brief")
        from utils.investor_brief_v2 import generate_investor_brief

        brief = generate_investor_brief(pkg)
        brief_section_count = len(brief.get("sections", []))

        _update_job(job_id, status="running", msg="Shareholder round")
        shareholder_round = run_shareholder_round(pkg, pitch)
        logger.info(
            "[Evaluate] {} | Shareholder round: {} responses",
            ctx,
            len(shareholder_round),
        )

        # Auto-trigger quarterly review hook: ≥2 NO-GO + high IRR → WARNING
        if shareholder_round:
            nogo_count = sum(
                1 for s in shareholder_round if s.get("verdict") == "NO-GO"
            )
            fe = pkg.financial_evaluation
            irr_base = fe.purchase.simple_irr_pct if (fe and fe.purchase) else None
            if nogo_count >= 2 and irr_base is not None and irr_base > 20:
                logger.warning(
                    "[Evaluate] {} High-IRR deal ({:.1f}%) with {} NO-GO shareholders — recommend quarterly board review",
                    ctx,
                    irr_base,
                    nogo_count,
                )

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
                job.shareholder_round = shareholder_round
                job.deal_id = deal_id
            _db_update_job(job)

        elapsed = _time_mod.time() - t0
        logger.info(
            "[Evaluate] {} complete | deal={} | {}memos/{}briefs | {:.1f}s",
            ctx,
            deal_id,
            memo_section_count,
            brief_section_count,
            elapsed,
        )

    except Exception as exc:
        elapsed = _time_mod.time() - t0
        logger.error("[Evaluate] {} failed at {:.1f}s: {}", ctx, elapsed, exc)
        _update_job(job_id, status="failed", error=str(exc))


def _update_job(
    job_id: str, status: str, msg: str = "", error: str | None = None
) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.status = status
            if msg:
                job.progress_msg = msg
            if error:
                job.error = error
            if status in ("complete", "failed"):
                job.completed_at = datetime.now(timezone.utc).isoformat()
        _db_update_job(job)


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
    _periodic_cleanup()
    job_id = str(uuid.uuid4())
    safe_sell_psf = sell_psf if sell_psf is not None else 0
    job = EvaluateJob(
        job_id=job_id,
        status="pending",
        survey_no=survey_no,
        market=market,
        land_area_sqft=land_area_sqft,
        sell_psf=safe_sell_psf,
        deal_type=deal_type,
        pitch=pitch,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    with _jobs_lock:
        _jobs[job_id] = job
    _db_insert_job(job)

    t = threading.Thread(
        target=_run_pipeline,
        args=(
            job_id,
            survey_no,
            market,
            land_area_sqft,
            safe_sell_psf,
            deal_type,
            pitch,
        ),
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
    _periodic_cleanup()
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            return job.to_dict()
    # Cache miss — fall back to DB (handles container restart)
    return _db_fetch_job(job_id)
