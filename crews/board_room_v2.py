"""
RE_OS — Board Room V2 (Sprint 64 — Decision Layer)
==================================================
IntelPackage-based Board Room. No DB calls inside. All data comes from the
IntelPackage passed at invocation. Five dept heads (BD, Finance, Engineering,
Ops, Legal) run concurrently via ThreadPoolExecutor, each acting as an
interpreter of the structured intel rather than a tool-calling agent.

Usage:
    pkg = IntelRegistry().get_full_picture("45/2", "Devanahalli", 5200, 6000)
    result = run_board_session_v2(pkg, pitch="5 acre Devanahalli JD deal")
    print(result.responses["bd"])
"""

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger

from config.llm_router import get_analysis_llm
from intelligence.registry import IntelPackage
from utils.intel_context import build_intel_context

__all__ = ["run_board_session_v2", "BoardSessionV2Result"]

_DEPT_TIMEOUT_S = 120


@dataclass
class BoardSessionV2Result:
    session_id: str
    survey_no: str
    market: str
    status: str
    responses: dict[str, str] = field(default_factory=dict)
    created_at: str = ""

    def __str__(self) -> str:
        return (
            f"[BoardSessionV2:{self.session_id[:8]}] "
            f"{self.market}/{self.survey_no} | "
            f"{len(self.responses)}/5 depts | {self.status}"
        )

    def __repr__(self) -> str:
        return (
            f"BoardSessionV2Result(session_id={self.session_id!r}, "
            f"survey_no={self.survey_no!r}, market={self.market!r}, "
            f"status={self.status!r}, depts={len(self.responses)})"
        )


_DEPT_PROMPTS: dict[str, str] = {
    "bd": (
        "You are the VP of Business Development at LLS. Your task is to evaluate "
        "a land acquisition opportunity using ONLY the structured intelligence below. "
        "Do not call any external tools. Do not query any database. "
        "All data you need is in this IntelPackage.\n\n"
        "Evaluate: market pulse (pricing, absorption, supply), financial feasibility "
        "(IRR for purchase/JD/JV structures), demand signals, developer landscape, "
        "and distressed developer opportunities.\n\n"
        "Structure your response:\n"
        "1. MARKET SUMMARY — avg PSF, MoS, supply/demand balance, momentum\n"
        "2. FINANCIAL VIABILITY — best deal structure, IRR, GDV, equity required\n"
        "3. RISKS — top 3 risks (market, execution, legal)\n"
        "4. UPSIDES — top 3 upsides\n"
        "5. VERDICT — GO / CONDITIONAL / NO-GO with rationale\n\n"
        "Every number must come from the IntelPackage below. Maximum 300 words."
    ),
    "finance": (
        "You are the VP of Finance & Capital Strategy at LLS. Your task is to "
        "assess deal viability using ONLY the structured intelligence below. "
        "No external tools. No DB queries.\n\n"
        "The IntelPackage contains full financial evaluation across purchase/JD/JV "
        "structures, IGR PSF source quality, and scenario analysis.\n\n"
        "Structure your response:\n"
        "1. DEAL STRUCTURE COMPARISON — IRR for each structure, best structure\n"
        "2. CAPITAL REQUIREMENT — equity, debt, land cost, GDV\n"
        "3. SOURCE OF TRUTH — PSF source quality (live_igr/fallback/listing_only)\n"
        "4. DOWNSIDE ANALYSIS — bear case IRR, drawdown risk\n"
        "5. VERDICT — GO (IRR>=20%) / MARGINAL (12-20%) / NO-GO (<12%)\n\n"
        "Cite exact numbers from the IntelPackage. Maximum 250 words."
    ),
    "engineering": (
        "You are the VP of Engineering & Technical Delivery at LLS. Your task is "
        "to assess technical feasibility using ONLY the structured intelligence below. "
        "No external tools. No DB queries.\n\n"
        "The IntelPackage contains land picture (zone, FAR, buildable area, green "
        "coverage, flood risk, development readiness) and market pulse.\n\n"
        "Structure your response:\n"
        "1. LAND PARAMETERS — area, zone, FAR, max floors\n"
        "2. BUILDABLE POTENTIAL — buildable sqft, sellable sqft, plot coverage\n"
        "3. ENVIRONMENTAL — green coverage %, BDA compliance, flood risk\n"
        "4. DEVELOPMENT READINESS — readiness level, infrastructure, flags\n"
        "5. VERDICT — FEASIBLE / CONDITIONAL / NOT_FEASIBLE\n\n"
        "Cite exact numbers from the IntelPackage. Maximum 250 words."
    ),
    "ops": (
        "You are the VP of Operations & Market Execution at LLS. Your task is "
        "to define the go-to-market playbook using ONLY the structured intelligence "
        "below. No external tools. No DB queries.\n\n"
        "The IntelPackage contains demand signals (momentum, absorption, RERA "
        "launch velocity), market pulse (inventory, pricing, developer landscape), "
        "and financial projections.\n\n"
        "Structure your response:\n"
        "1. MARKET CONDITIONS — demand signal, absorption, supply label\n"
        "2. COMPETITIVE LANDSCAPE — unique developers, Grade-A presence\n"
        "3. SALES VELOCITY PROJECTION — implied monthly units, absorption rate\n"
        "4. CHANNEL STRATEGY — buyer profile based on PSF band and deal type\n"
        "5. VERDICT — GREEN / AMBER / RED for execution feasibility\n\n"
        "Cite exact numbers from the IntelPackage. Maximum 250 words."
    ),
    "legal": (
        "You are the VP of Legal & Compliance at LLS. Your task is to assess "
        "legal and regulatory risk using ONLY the structured intelligence below. "
        "No external tools. No DB queries.\n\n"
        "The IntelPackage contains legal picture (zone risk, title risk flags, "
        "encumbrance, litigation, land use conversion, overlay constraints, "
        "inheritance risk) and market pulse.\n\n"
        "Structure your response:\n"
        "1. TITLE RISK — risk level, each flag with status (CLEAR/WARNING/RISK)\n"
        "2. REGULATORY — zone, overlay constraints, conversion requirements\n"
        "3. LITIGATION & ENCUMBRANCE — litigation risk, guidance value vs market\n"
        "4. KEY CONCERNS — top 2-3 items requiring legal due diligence\n"
        "5. VERDICT — CLEAR / CONDITIONAL / BLOCKED\n\n"
        "Cite exact flags from the IntelPackage. Maximum 250 words."
    ),
}


def _build_agent(role: str, goal: str, backstory: str):
    from crewai import Agent
    return Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        llm=get_analysis_llm(),
        max_iter=2,
        allow_delegation=False,
        verbose=False,
    )


_AGENT_DEFS: dict[str, tuple[str, str, str]] = {
    "bd": (
        "VP — Business Development & Investment Decisions",
        "Evaluate market pitch and deliver GO/NO-GO using structured IntelPackage data.",
        "Sharp, numbers-first real-estate operator who turns structured intelligence "
        "into investment decisions. Interprets market pulse, financial scenarios, "
        "demand signals, and developer landscape from structured data packages. "
        "All analysis is grounded in the IntelPackage — no external tool calls needed."
    ),
    "finance": (
        "VP — Finance & Capital Strategy",
        "Assess deal viability, break-even PSF, IRR range, and funding structure from IntelPackage.",
        "Conservative finance leader who evaluates feasibility from structured financial "
        "intelligence. Analyses purchase/JD/JV scenarios, PSF source quality, and "
        "capital requirements from the IntelPackage. Never makes up numbers — every "
        "figure cited comes from the structured data."
    ),
    "engineering": (
        "VP — Engineering & Technical Delivery",
        "Assess technical feasibility from IntelPackage land picture and market pulse.",
        "Principal architect-engineer who translates land intelligence into buildable "
        "reality. Evaluates zone, FAR, green coverage, flood risk, and development "
        "readiness from the IntelPackage data. Flags approval bottlenecks and design "
        "assumptions against the provided data."
    ),
    "ops": (
        "VP — Operations & Market Execution",
        "Define go-to-market playbook from IntelPackage demand signals and market pulse.",
        "Operations director who turns demand intelligence into execution strategy. "
        "Analyses absorption velocity, competitive landscape, and sales projections "
        "from the IntelPackage. Every KPI and channel recommendation is data-grounded."
    ),
    "legal": (
        "VP — Legal & Compliance",
        "Assess legal and regulatory risk from IntelPackage legal picture.",
        "Detail-oriented legal researcher who evaluates title risk, zone compliance, "
        "overlay constraints, and encumbrance from the IntelPackage. Flags every "
        "unresolved item with the applicable Karnataka statute. All findings are "
        "sourced from the structured legal intelligence."
    ),
}


def _run_dept_heads(pkg: IntelPackage, pitch: str) -> dict[str, str]:
    from crewai import Task, Crew, Process

    context = build_intel_context(pkg)
    ctx_json = json.dumps(context, indent=2, default=str)
    pitch_stripped = (pitch or "").strip()[:2000]

    def run_single(key: str) -> str:
        role, goal, backstory = _AGENT_DEFS[key]
        agent = _build_agent(role, goal, backstory)
        prompt = _DEPT_PROMPTS[key]

        task_desc = (
            f"PITCH: {pitch_stripped}\n\n"
            f"MARKET: {pkg.market}\n"
            f"SURVEY: {pkg.survey_no}\n\n"
            f"{prompt}\n\n"
            f"=== INTELLIGENCE PACKAGE ===\n"
            f"{ctx_json}\n"
        )

        task = Task(
            description=task_desc,
            expected_output=(
                "A structured department assessment with numbered sections, "
                "exact numbers from the IntelPackage, and a clear verdict."
            ),
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        result = crew.kickoff()
        if hasattr(result, "tasks_output") and result.tasks_output:
            return result.tasks_output[0].raw or ""
        return getattr(result, "raw", str(result))

    responses: dict[str, str] = {}
    keys = list(_AGENT_DEFS.keys())
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(run_single, k): k for k in keys}
        try:
            for future in as_completed(future_map, timeout=_DEPT_TIMEOUT_S):
                k = future_map[future]
                try:
                    responses[k] = future.result()
                except Exception as exc:
                    responses[k] = f"[{k.upper()} HEAD] Error: {exc}"
                    logger.warning("[BoardRoomV2] dept '%s' failed: %s", k, exc)
        except FuturesTimeoutError:
            for f in future_map:
                f.cancel()
            logger.warning("[BoardRoomV2] dept-head timeout — partial responses")
    return responses


def run_board_session_v2(
    pkg: IntelPackage,
    pitch: str = "",
    session_id: str | None = None,
) -> BoardSessionV2Result:
    sid = session_id or str(uuid.uuid4())
    start = time.perf_counter()
    responses = _run_dept_heads(pkg, pitch)
    elapsed = time.perf_counter() - start

    result = BoardSessionV2Result(
        session_id=sid,
        survey_no=pkg.survey_no,
        market=pkg.market,
        status="complete" if len(responses) >= 3 else "partial",
        responses=responses,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    logger.info(
        "[BoardRoomV2] %s | %d/%d depts | %.1fs",
        sid[:8], len(responses), len(_AGENT_DEFS), elapsed,
    )
    return result
