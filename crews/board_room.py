"""
RE_OS — Board Room Crew
───────────────────────
POST /api/board/session → creates session row, fires 5 dept-head agents
(BD, Finance, Engineering, Ops, Legal) in a background thread, returns
session_id immediately.
GET  /api/board/session/<id> → polls DB for pending|active|complete|failed.

Dept heads run concurrently via ThreadPoolExecutor with a 90-second timeout
guard. Each is a single-agent CrewAI Crew.

T-347: Legal Head (5th dept) added — RERA/BDA/title compliance lens.
"""

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import text

from config.llm_router import get_analysis_llm, get_heavy_llm
from agents.board_room.legal_head import build_legal_head_agent
from utils.db import get_engine
from utils.fsi_calculator import calculate_fsi, recommend_unit_mix
from utils.board_room_eval import BoardRoomEvaluator
from utils.green_coverage import calculate_green_coverage
from utils.irr_model import compare_scenarios, GDVEstimator, log_igr_lookup
from utils.distressed_developer import DistressedDeveloperScanner

# Shared regex patterns for pitch parsing (used by engineering + finance auto-calc)
_ACRE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-\s*)?acres?", re.I)
_SQFT_RE = re.compile(
    r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:sq\s*\.?\s*ft|sqft|square\s*feet|sft)",
    re.I,
)
_PSF_RE  = re.compile(
    # Alternative 1: prefix (psf/per sq ft/Rs/₹) before number
    r"(?:(?:psf|per\s+sq\.?\s*ft|Rs\.?\s*|[\u20B9])\s*(\d+(?:,\d{3})*(?:\.\d+)?)|"
    # Alternative 2: number before "psf" suffix
    r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*psf)",
    re.I,
)

# Pitch auto-calc constants
_ACRE_TO_SQFT: float = 43560.0
_DEFAULT_GUIDANCE_PSF: float = 4000.0
_DEFAULT_NEG_DISCOUNT_PCT: float = 10.0
_DEFAULT_FSI_EFFICIENCY: float = 0.65
_DEFAULT_FSI_VALUE: float = 2.5
_DEFAULT_PSF_BY_MARKET: dict = {
    "Yelahanka": 6500, "Devanahalli": 5500, "Hebbal": 7500,
}


def _parse_psf(match: re.Match) -> float:
    """Extract PSF value from a bidirectional PSF regex match (selects whichever group matched)."""
    raw = match.group(1) or match.group(2)
    return float(raw.replace(",", ""))


def _pitch_mentions_land(pitch: str) -> bool:
    """Return True if pitch mentions land/development/acquisition keywords.
    Used to skip expensive DB lookups when pitch is unrelated."""
    return bool(re.search(
        r"\b(land|site|acre|acres|sq\.?\s*ft|sqft|development|"
        r"project|acquisition|purchase|buy|invest|enter|entry|"
        r"plot|parcel|survey)\b", pitch, re.I
    ))


def _query_market_supply(market: str) -> tuple[str, str]:
    """Query v_market_brief_mat for months_of_supply. Returns (months_str, label).
    Returns ('N/A', 'N/A') on failure or empty market."""
    market = (market or "").strip()
    if not market:
        return "N/A", "N/A"
    try:
        from utils.db import get_engine as _ge, db_query_duration_seconds
        from sqlalchemy import text as _st
        with _ge().connect() as _c:
            with db_query_duration_seconds.labels(query_name="v_market_brief_mat").time():
                row = _c.execute(
                    _st("SELECT months_of_supply, supply_label FROM v_market_brief_mat WHERE micro_market ILIKE :m LIMIT 1"),
                    {"m": f"%{market}%"},
                ).fetchone()
            if row:
                months_str = str(row[0]) if row[0] is not None else "N/A"
                return months_str, str(row[1]) if row[1] else "N/A"
    except Exception:
        pass
    return "N/A", "N/A"


def _extract_pitch_params(pitch: str) -> dict:
    """Single-pass extraction of area and PSF from a pitch string.
    Returns dict with 'area_sqft' (float or None), 'acreage' (float or None), 'psf' (float or None)."""
    area_match = _ACRE_RE.search(pitch)
    sqft_match = _SQFT_RE.search(pitch)
    psf_match = _PSF_RE.search(pitch)
    area_sqft = None
    acreage = None
    if area_match:
        acreage = float(area_match.group(1))
        area_sqft = acreage * _ACRE_TO_SQFT
    elif sqft_match:
        area_sqft = float(sqft_match.group(1).replace(",", ""))
    psf = _parse_psf(psf_match) if psf_match else None
    return {"area_sqft": area_sqft, "acreage": acreage, "psf": psf}


# ── Data contract ─────────────────────────────────────────────────────────────

@dataclass
class BoardSession:
    session_id: str
    pitch: str
    market: Optional[str] = None
    status: str = "pending"          # pending | active | complete | failed
    ceo_decomposition: Optional[str] = None
    bd_response: Optional[str] = None
    engineering_response: Optional[str] = None
    finance_response: Optional[str] = None
    operations_response: Optional[str] = None
    legal_response: Optional[str] = None
    actions: list = field(default_factory=list)
    created_at: Optional[str] = None


def _ceo_decompose(pitch: str, market: str, _session_excluded: set) -> Optional[dict]:
    """Use the CEO agent to decompose the pitch into 5 dept-specific sub-questions.
    Returns a dict with keys 'bd', 'finance', 'engineering', 'ops', 'legal'
    or None on failure.
    _session_excluded: per-session provider exclusion set — never touches the global _EXCLUDED.
    """
    try:
        llm = get_heavy_llm(excluded=_session_excluded)

        mos_context = ""
        try:
            from utils.db import get_engine as _mos_ge, db_query_duration_seconds
            from sqlalchemy import text as _mos_st
            with _mos_ge().connect() as _mos_c:
                with db_query_duration_seconds.labels(query_name="v_market_brief_mat").time():
                    _mos_row = _mos_c.execute(
                        _mos_st("SELECT months_of_supply, supply_label FROM v_market_brief_mat WHERE micro_market ILIKE :m LIMIT 1"),
                        {"m": f"%{market}%"},
                    ).fetchone()
                if _mos_row and _mos_row[0] is not None:
                    mos_context = f"Market supply: {_mos_row[0]} months ({_mos_row[1]})"
                    if _mos_row[1] == "OVERSUPPLY":
                        mos_context += " — ⚠ OVERSUPPLY: flag in recommendation, caution on new entry timing"
        except Exception:
            pass

        mos_line = f"\n{mos_context}\n" if mos_context else ""
        prompt = (
            f"You are the CEO of a real estate investment firm. Given the following pitch for a market, "
            f"decompose it into five specific sub-questions, one for each department head: "
            f"Business Development (BD), Finance, Engineering, Operations, and Legal. "
            f"Each sub-question should be tailored to that department's expertise and concerns. "
            f"Return ONLY a JSON object with exactly five keys: 'bd', 'finance', 'engineering', 'ops', 'legal'. "
            f"Each value should be a string containing the sub-question for that department. "
            f"Do not include any extra text or explanation.\n\n"
            f"Market: {market}\n"
            f"Pitch: {pitch}\n"
            f"{mos_line}"
        )
        response = llm.call(prompt)
        # Try to parse the JSON
        decomposed = json.loads(response)
        # Validate that we have the five keys and they are strings
        if isinstance(decomposed, dict) and all(k in decomposed for k in ("bd", "finance", "engineering", "ops", "legal")):
            # Ensure each value is a string (or convert to string)
            for key in ("bd", "finance", "engineering", "ops", "legal"):
                if not isinstance(decomposed[key], str):
                    decomposed[key] = str(decomposed[key])
            return decomposed
        else:
            logger.warning(f"board_room: CEO decomposition returned invalid structure: {decomposed}")
            return None
    except Exception as exc:
        logger.warning(f"board_room: CEO decomposition failed: {exc}")
        return None


# ── DB helpers ────────────────────────────────────────────────────────────────

_DEPT_TASK_TEMPLATES = {
    "bd": (
        "You are the BD Head reviewing a real estate pitch.\n"
        "Market: {market}\n"
        "CEO Sub-question: {dept_question}\n\n"
        "Deliver:\n"
        "1. GO / NO-GO verdict with one-sentence rationale\n"
        "2. Absorption rate signal for this market (cite a number)\n"
        "3. Three specific risks (each: risk + who it hurts)\n"
        "4. Three specific upsides (each: upside + magnitude estimate)\n"
        "5. Recommended entry PSF range for LLS"
    ),
    "finance": (
        "You are the Finance Head reviewing a real estate pitch.\n"
        "Market: {market}\n"
        "CEO Sub-question: {dept_question}\n\n"
        "Deliver:\n"
        "1. VIABLE / CONDITIONAL / UNVIABLE verdict\n"
        "2. Break-even PSF calculation (land cost + construction + margin)\n"
        "3. IRR range estimate (base / bull / bear scenario)\n"
        "4. Key financial risk and its quantified impact\n"
        "5. Recommended financial structure (equity/debt split)"
    ),
    "engineering": (
        "You are the Engineering Head reviewing a real estate pitch.\n"
        "Market: {market}\n"
        "CEO Sub-question: {dept_question}\n\n"
        "Deliver:\n"
        "1. FEASIBLE / CONDITIONAL / NOT_FEASIBLE verdict\n"
        "2. Top 3 regulatory or approval blockers (RERA, BDA, BBMP, STRR)\n"
        "3. Construction cost risk (₹/sqft range + key driver)\n"
        "4. Recommended product mix (1BHK/2BHK/3BHK % split) for this market\n"
        "5. Timeline estimate from land acquisition to RERA registration"
    ),
    "ops": (
        "You are the Operations Head reviewing a real estate pitch.\n"
        "Market: {market}\n"
        "CEO Sub-question: {dept_question}\n\n"
        "Deliver:\n"
        "1. Recommended channel mix (channel partner % / direct % / digital %)\n"
        "2. Quarterly sales velocity assumption (units/quarter)\n"
        "3. Three launch KPIs with target numbers\n"
        "4. Biggest operational risk in this market\n"
        "5. Suggested launch window (month + rationale)"
    ),
    "legal": (
        "You are the Legal Head reviewing a real estate pitch.\n"
        "Market: {market}\n"
        "CEO Sub-question: {dept_question}\n\n"
        "The following auto-computed legal context has been prepended to your question "
        "— it contains DB-sourced zone risk, developer RERA record, and guidance value data. "
        "Cite specific numbers from this data in your response.\n\n"
        "Respond as Legal Head. Lead with CLEAR / RISK / BLOCKED.\n"
        "Cover: RERA registration status (cite the developer's project count, delay rate, "
        "and compliance signal from the auto-context), BDA/BBMP layout approval, "
        "title chain, encumbrance (cite guidance gap % if available), "
        "agricultural conversion (if applicable), regulatory overlay risks "
        "(airport zone, green belt, lake buffer, high-tension line, rajakaluve).\n"
        "Name every unresolved item with the applicable Karnataka statute or authority.\n"
        "Maximum 250 words."
    ),
}


def _build_bd_agent():
    from crewai import Agent

    return Agent(
        role="VP — Business Development & Investment Decisions",
        goal="Evaluate market pitch and deliver GO/NO-GO with 3 risks and 3 upsides.",
        backstory="""Sharp, numbers-first real-estate operator who turns noisy market intelligence into investment decisions.
        Tracks absorption, competitor launches, developer credibility, pricing power, and land-entry timing.
        Uses distressed developer signals as JD/JV opportunity indicators — delayed projects, complaints, and
        low project count are early distress markers. Challenges every optimistic assumption and converts field
        signals into a clear GO/NO-GO recommendation.""",
        llm=get_analysis_llm(),
        max_iter=2,
        allow_delegation=False,
        verbose=False,
    )


def _build_finance_agent():
    from crewai import Agent

    return Agent(
        role="VP — Finance & Capital Strategy",
        goal="Assess deal viability, break-even PSF, IRR range, downside risk, and funding structure.",
        backstory="""Conservative finance leader focused on margin of safety, cash conversion, land-cost discipline,
        debt exposure, and scenario-adjusted returns. Converts market pitch assumptions into capital allocation logic.""",
        llm=get_analysis_llm(),
        max_iter=2,
        allow_delegation=False,
        verbose=False,
    )


def _build_engineering_agent():
    from crewai import Agent

    return Agent(
        role="VP — Engineering & Technical Delivery",
        goal="Assess feasibility and technical risks of land pitches, providing FEASIBLE/CONDITIONAL/NOT_FEASIBLE verdict with engineering budget delta.",
        backstory="""Principal architect-engineer who translates market intel into buildable reality.
        Understands FAR, setbacks, septic systems, road access constraints, BDA masterplan zones, and RERA compliance.
        Flags approval bottlenecks and design assumptions that could consume margin before ground is broken.""",
        llm=get_analysis_llm(),
        max_iter=2,
        allow_delegation=False,
        verbose=False,
    )


def _build_ops_agent():
    from crewai import Agent

    return Agent(
        role="VP — Operations & Market Execution",
        goal="Define the go-to-market playbook: channel strategy, sales velocity assumption, partner network, and KPIs.",
        backstory="""Operations director experienced in Bengaluru residential launches. Treats every project as a sales problem first
        and construction problem second. Interrogates buyer profile, launch differentiation, channel mix, partner readiness,
        quarterly sales velocity, and Day-1 execution KPIs.""",
        llm=get_analysis_llm(),
        max_iter=2,
        allow_delegation=False,
        verbose=False,
    )


_DEPT_RESPONSE_TIMES: dict[str, list[float]] = {
    k: [] for k in ("bd", "finance", "engineering", "ops", "legal")
}


def _dept_response_times() -> dict:
    """Return median response time per dept for health monitoring."""
    import statistics
    result = {}
    for dept, times in _DEPT_RESPONSE_TIMES.items():
        if times:
            result[dept] = {
                "median_s": round(statistics.median(times), 1),
                "count": len(times),
            }
    return result


def _run_dept_heads(pitch: str, market: str, decomposition: Optional[dict] = None,
                    _session_excluded: set = None) -> dict:
    """Run five department-head agents (BD, Finance, Engineering, Ops, Legal) concurrently.
    Returns a dict with keys 'bd', 'finance', 'engineering', 'ops', 'legal'.
    Enforces a 90-second timeout guard.
    Tracks per-dept response time in _DEPT_RESPONSE_TIMES for health monitoring.
    _session_excluded: per-session exclusion set — never mutates global _EXCLUDED.
    """
    from crewai import Task, Crew, Process
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

    _excl = _session_excluded if _session_excluded is not None else set()

    def run_single_agent(builder_fn, key: str) -> str:
        _start_s = time.time()
        agent = builder_fn()
        dept_question = (
            decomposition.get(key, "").strip()
            if decomposition and isinstance(decomposition.get(key), str)
            else ""
        ) or pitch

        if key == "bd":
            bd_context = ""
            market_safe = (market or "").strip()
            if market_safe and _pitch_mentions_land(pitch):
                try:
                    scanner = DistressedDeveloperScanner()
                    top = scanner.top_n(market_safe, n=3, min_score=0.3)
                    if top:
                        lines = [f"\n\n[DISTRESSED DEVELOPERS in {market_safe} — JD/JV targets]"]
                        for i, d in enumerate(top, 1):
                            lines.append(
                                f"  {i}. {d.developer_name} — score {d.distress_score:.2f} "
                                f"({d.alert_level}), {d.delayed_projects} delayed, "
                                f"{d.complaint_count} complaints"
                            )
                        bd_context = "\n".join(lines) + "\n"
                        logger.info("[board_room] BD context: {} distressed dev(s) in {}",
                                    len(top), market_safe)
                    else:
                        logger.debug("[board_room] No distressed developers found in {}", market_safe)
                except Exception:
                    logger.debug("[board_room] Distressed dev lookup failed for {}", market_safe)

            # Infrastructure score (T-718) — only for land-related pitches (expensive: DB + OSM)
            if market_safe and _pitch_mentions_land(pitch):
                try:
                    from utils.infrastructure_scorer import InfrastructureScorer
                    from utils.db import get_engine as _infra_ge
                    from sqlalchemy import text as _infra_st
                    with _infra_ge().connect() as _infra_c:
                        _centroid = _infra_c.execute(
                            _infra_st("SELECT ST_X(centroid::geometry), ST_Y(centroid::geometry) FROM micro_markets WHERE name ILIKE :m LIMIT 1"),
                            {"m": f"%{market_safe}%"},
                        ).fetchone()
                    if _centroid:
                        _lng, _lat = float(_centroid[0]), float(_centroid[1])
                        _scorer = InfrastructureScorer()
                        _infra_r = _scorer.score(_lat, _lng, market_safe)
                        logger.info("[board_room] Infrastructure score for {}: metro={}m NH44={}m BIAL={}km walk={}/10",
                                     market_safe,
                                     _infra_r.dist_to_nearest_metro_m or "N/A",
                                     _infra_r.dist_to_nh44_m or "N/A",
                                     _infra_r.dist_to_bial_km or "N/A",
                                     _infra_r.walkability_score or "N/A")
                        bd_context += (
                            f"\n[INFRASTRUCTURE — {market_safe}] "
                            f"Metro: {_infra_r.dist_to_nearest_metro_m or 'N/A'}m | "
                            f"NH-44: {_infra_r.dist_to_nh44_m or 'N/A'}m | "
                            f"BIAL: {_infra_r.dist_to_bial_km or 'N/A'}km | "
                            f"CBD: {_infra_r.dist_to_cbd_km or 'N/A'}km | "
                            f"Walkability: {_infra_r.walkability_score or 'N/A'}/10\n"
                        )
                except Exception:
                    logger.debug("[board_room] Infrastructure score failed for %s", market_safe)

            # months_of_supply signal for BD (T-485)
            if market_safe:
                mos_val, mos_label = _query_market_supply(market_safe)
                if mos_label not in ("N/A", "INSUFFICIENT_DATA"):
                    bd_context += (
                        f"\n[INVENTORY SIGNAL — {market_safe}] "
                        f"Inventory signal: {mos_val} months ({mos_label})\n"
                    )

            dept_question = bd_context + dept_question

        if key == "engineering":
            params = _extract_pitch_params(pitch)
            if params["area_sqft"] is not None:
                sqft = params["area_sqft"]
                psf_val = params["psf"] if params["psf"] is not None else _DEFAULT_PSF_BY_MARKET.get(market, 6500)
                fsi_r = calculate_fsi(sqft, zone="R2", market=market)
                mix_r = recommend_unit_mix(psf_val)
                gc_r = calculate_green_coverage(sqft, fsi_r.plot_coverage)
                area_label = (
                    f"{params['acreage']} acres / {sqft:,.0f} sqft"
                    if params["acreage"]
                    else f"{sqft:,.0f} sqft / {sqft/_ACRE_TO_SQFT:.2f} acres"
                )
                dept_question = (
                    f"\n\n[AUTO FSI CALC — {area_label}, Zone R2, ₹{psf_val:,.0f} PSF]\n"
                    f"Buildable: {fsi_r.buildable_area_sqft:,.0f} sqft | "
                    f"Sellable: {fsi_r.sellable_area_sqft:,.0f} sqft | "
                    f"Max floors: {fsi_r.max_floors} | "
                    f"Unit mix: {mix_r.bhk_1_pct}% 1BHK / {mix_r.bhk_2_pct}% 2BHK / {mix_r.bhk_3_pct}% 3BHK | "
                    f"Green coverage: {gc_r.green_pct}% ({gc_r.tree_count} trees, BDA min met: {gc_r.meets_bda_minimum})\n"
                ) + dept_question

        if key == "finance":
            irr_context = ""
            market_safe = (market or "").strip()
            if market_safe:
                try:
                    from utils.psf_forecaster import PSFForecaster
                    fc = PSFForecaster()
                    forecast = fc.predict(market_safe)
                    if forecast and len(forecast) >= 3:
                        psf_now = forecast[0].predicted_psf
                        psf_1m = forecast[1].predicted_psf if len(forecast) > 1 else psf_now
                        psf_3m = forecast[2].predicted_psf if len(forecast) > 2 else psf_now
                        direction = "up" if psf_3m > psf_now else ("down" if psf_3m < psf_now else "stable")
                        irr_context += (
                            f"\n\n[PSF FORECAST — {market_safe}]\n"
                            f"Current PSF: ₹{psf_now:,.0f} | "
                            f"1-month: ₹{psf_1m:,.0f} | "
                            f"3-month: ₹{psf_3m:,.0f} | "
                            f"Direction: {direction}\n"
                        )
                except Exception:
                    logger.debug("[board_room] PSF forecast lookup failed for %s", market_safe)
            params = _extract_pitch_params(pitch)
            if params["area_sqft"] is not None and params["psf"] is not None:
                try:
                    sqft = params["area_sqft"]
                    sell_psf = params["psf"]
                    market_safe = (market or "").strip()
                    sellable = sqft * _DEFAULT_FSI_EFFICIENCY * _DEFAULT_FSI_VALUE

                    igr_psf_used = False
                    igr_source = None
                    igr_count = 0
                    if market_safe:
                        try:
                            est = GDVEstimator()
                            gdv_r = est.estimate(sellable, market_safe)
                            if gdv_r.igr_source and gdv_r.igr_record_count >= GDVEstimator.MIN_IGR_RECORDS:
                                sell_psf = gdv_r.sell_psf
                                igr_psf_used = True
                                igr_source = gdv_r.igr_source
                                igr_count = gdv_r.igr_record_count
                                log_igr_lookup(market_safe, igr_source, igr_count, gdv_r.sell_psf,
                                               "BoardRoomFinance")
                        except Exception:
                            logger.debug("[board_room] IGR PSF lookup failed, using pitch PSF")

                    land_cost = sqft * _DEFAULT_GUIDANCE_PSF * (1 - _DEFAULT_NEG_DISCOUNT_PCT / 100)
                    scenarios = compare_scenarios(land_cost, sellable, sell_psf)

                    psf_source_note = ""
                    if igr_psf_used:
                        psf_source_note = f" (IGR transaction PSF — {igr_count} records)"
                    elif not market_safe:
                        psf_source_note = " (listing PSF — no market for IGR lookup)"

                    best_irr = scenarios.bull.simple_irr_pct
                    base_irr = scenarios.base.simple_irr_pct
                    worst_irr = scenarios.bear.simple_irr_pct
                    drawdown = scenarios.base.max_drawdown_pct
                    sharpe = scenarios.base.sharpe_ratio
                    irr_context = (
                        f"\n\n[AUTO IRR CALC — {sqft:,.0f} sqft site, ₹{sell_psf:,.0f} PSF{psf_source_note}]\n"
                        f"Base IRR: {base_irr:.1f}% ({scenarios.base.verdict}) | "
                        f"Bull: {best_irr:.1f}% | "
                        f"Bear: {worst_irr:.1f}% ({scenarios.bear.verdict})\n"
                        f"Risk bands: best {best_irr:.1f}% / base {base_irr:.1f}% / worst {worst_irr:.1f}%"
                        f", max drawdown {drawdown:.1f}%, Sharpe {sharpe:.2f}\n"
                        f"Land cost est.: ₹{scenarios.base.land_cost/1e7:.1f}Cr | "
                        f"GDV est.: ₹{scenarios.base.gdv/1e7:.1f}Cr\n"
                        f"Recommendation: {scenarios.recommendation}\n"
                    )
                except Exception as exc:
                    logger.warning("[board_room] finance auto-IRR calc failed for market=%s pitch=%s: %s",
                                   market, pitch[:80], exc)
                    irr_context = (
                        f"\n\n[AUTO IRR CALC — {sqft:,.0f} sqft site, ₹{sell_psf:,.0f} PSF]\n"
                        f"[IRR computation failed — {exc}]. Finance assessment will be based on LLM reasoning alone."
                        f"\n"
                    )

            # months_of_supply signal from v_market_brief_mat (T-485)
            if market_safe:
                mos_val, mos_label = _query_market_supply(market_safe)
                if mos_label not in ("N/A", "INSUFFICIENT_DATA"):
                    irr_context += (
                        f"\n[INVENTORY SIGNAL — {market_safe}] "
                        f"Inventory signal: {mos_val} months ({mos_label}) — "
                        f"{'buyer' if mos_label == 'UNDERSUPPLY' else 'seller' if mos_label == 'OVERSUPPLY' else 'balanced'}" 
                        f" market conditions\n"
                    )

            # GV source + freshness (Sprint 78 — GATE-78)
            gv_source_context = ""
            try:
                from utils.db import get_engine as _gv_engine
                from sqlalchemy import text as _gv_text
                if market_safe:
                    with _gv_engine().connect() as _gv_c:
                        _gv_row = _gv_c.execute(
                            _gv_text("""
                                SELECT gv.data_source, gv.gazette_year,
                                       gv.extraction_confidence, gv.guidance_value_psf
                                FROM guidance_values gv
                                JOIN micro_markets mm ON mm.id = gv.micro_market_id
                                WHERE mm.name ILIKE :m
                                  AND gv.data_source IN ('gazette_pdf', 'portal_scraped')
                                ORDER BY gv.extraction_confidence DESC, gv.gazette_year DESC
                                LIMIT 1
                            """),
                            {"m": f"%{market_safe}%"},
                        ).fetchone()
                    if _gv_row:
                        ds = _gv_row[0] or "unknown"
                        gy = _gv_row[1]
                        conf = _gv_row[2] or 0.0
                        psf = _gv_row[3] or 0.0
                        from datetime import date as _gv_date
                        cy = _gv_date.today().year
                        months_old = (cy - gy) * 12 if gy else 0
                        gv_source_context = (
                            f"\n[GUIDANCE VALUE SOURCE: {ds} | "
                            f"Gazette year: {gy} | "
                            f"Age: {months_old} months | "
                            f"PSF: ₹{psf:,.0f} | "
                            f"Confidence: {conf:.0%}]\n"
                        )
                        if ds == "gazette_pdf" and months_old > 18:
                            gv_source_context += (
                                "WARNING: Guidance values are stale (>18 months). "
                                "Explicitly flag this limitation in your feasibility statement.\n"
                            )
                        logger.info(
                            "[board_room] GV context injected for {}: source={}, year={}, months_old={}",
                            market, ds, gy, months_old,
                        )
            except Exception as _gv_exc:
                logger.debug("[board_room] GV source lookup failed for {}: {}", market, _gv_exc)

            dept_question = gv_source_context + irr_context + dept_question

        if key == "legal":
            legal_context = ""
            try:
                from utils.rera_compliance_checker import check_developer_compliance
                from utils.zone_risk_checker import check_zone_risk
                from utils.kaveri_encumbrance import check_encumbrance
                params = _extract_pitch_params(pitch)

                # Detect developer — DB primary, regex fallback
                dev_match = None
                try:
                    from utils.db import get_engine as _get_engine
                    from sqlalchemy import text as _sa_text
                    first_word = (pitch.split()[0] if pitch.split() else "").rstrip(",:;.!?")
                    with _get_engine().connect() as _conn:
                        _row = _conn.execute(
                            _sa_text("SELECT name FROM developers WHERE name ILIKE :name LIMIT 1"),
                            {"name": f"%{first_word}%"},
                        ).fetchone()
                        if _row:
                            dev_match = type("_RegexStub", (), {"group": lambda s, _: _row[0]})()
                            logger.info("[board_room] developer detected via DB: %s", _row[0])
                except Exception as _db_exc:
                    logger.debug("[board_room] developer DB lookup failed: {}", _db_exc)
                if not dev_match:
                    dev_match = re.search(
                        r"\b(Brigade|Prestige|Sobha|Godrej|Adarsh|Salarpuria"
                        r"|Shriram|Mantri|Puravankara|Total Environment"
                        r"|Embassy|Concorde|Assetz)\b",
                        pitch, re.I
                    )

                # Detect zone from pitch text
                zone_match = re.search(
                    r"(?:zone|zoning)\s*(?::|is|=)?\s*(R[12]|C1)", pitch, re.I
                )
                detected_zone = (zone_match.group(1) if zone_match else "R2").upper()

                zone_r = check_zone_risk(market, zone=detected_zone)
                zone_txt = (
                    f"Zone {detected_zone} risk: {zone_r.risk_level}"
                    f"{' — overlays: ' + ', '.join(zone_r.overlay_risks) if zone_r.overlay_risks else ' — no overlay restrictions'}"
                )

                dev_txt = ""
                if dev_match:
                    dev_name = dev_match.group(1)
                    rera_r = check_developer_compliance(dev_name, market=market)
                    dev_txt = (
                        f"\n[RERA RECORD — {dev_name}] "
                        f"Projects: {rera_r.total_projects} | Delayed: {rera_r.delayed_projects} "
                        f"| Avg delay: {rera_r.avg_delay_months}mo | Signal: {rera_r.compliance_signal}"
                    )
                    if rera_r.inactive_anomalies:
                        dev_txt += f"\n⚠ {len(rera_r.inactive_anomalies)} project(s) inactive/cancelled"

                # Encumbrance — isolated try/except so a failure here doesn't lose zone/dev data
                enc_txt = ""
                try:
                    enc_r = check_encumbrance(market)
                    if enc_r.avg_guidance_value_psf:
                        enc_txt = (
                            f"\n[GUIDANCE VALUES — {market}] "
                            f"Avg GV: ₹{enc_r.avg_guidance_value_psf:,.0f}/sqft"
                        )
                    if enc_r.avg_transaction_psf:
                        enc_txt += (
                            f" | Avg Txn PSF: ₹{enc_r.avg_transaction_psf:,.0f}"
                        )
                    if enc_r.guidance_gap_pct is not None:
                        enc_txt += f" | Gap: {enc_r.guidance_gap_pct:+.1f}%"
                    if enc_r.risk_flags:
                        enc_txt += f"\n⚠ Encumbrance flags: {'; '.join(enc_r.risk_flags)}"
                except Exception as enc_exc:
                    logger.warning("[board_room] encumbrance auto-context failed: %s", enc_exc)

                legal_context = f"\n\n[AUTO LEGAL CONTEXT — {market} | Zone {detected_zone}]\n{zone_txt}{dev_txt}{enc_txt}\n"
            except ImportError as imp_exc:
                logger.error("[board_room] legal module import failed — check dependencies: %s", imp_exc)
            except Exception as exc:
                logger.warning("[board_room] legal auto-context failed: %s", exc)
            dept_question = legal_context + dept_question

        template = _DEPT_TASK_TEMPLATES.get(key)
        task_description = template.format(market=market, dept_question=dept_question) if template else (
            f"Market: {market}\nSub-question: {dept_question}\n\n"
            "Provide a structured one-page assessment with a clear verdict."
        )

        task = Task(
            description=task_description,
            expected_output=(
                "A structured assessment with: verdict (GO/NO-GO or VIABLE/CONDITIONAL/UNVIABLE or FEASIBLE/CONDITIONAL/NOT_FEASIBLE), "
                "numbered supporting points, and at least one specific number per point."
            ),
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        result = crew.kickoff()
        _elapsed = time.time() - _start_s
        _DEPT_RESPONSE_TIMES[key].append(_elapsed)
        if hasattr(result, "tasks_output") and result.tasks_output:
            return result.tasks_output[0].raw or ""
        return getattr(result, "raw", str(result))

    builders = {
        "bd": _build_bd_agent,
        "finance": _build_finance_agent,
        "engineering": _build_engineering_agent,
        "ops": _build_ops_agent,
        "legal": build_legal_head_agent,
    }
    responses: dict = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_key = {executor.submit(run_single_agent, fn, key): key for key, fn in builders.items()}
        try:
            for future in as_completed(future_to_key, timeout=90):
                key = future_to_key[future]
                try:
                    responses[key] = future.result()
                except Exception as exc:
                    responses[key] = f"[{key.upper()} HEAD] Error processing request — check logs for details."
                    logger.warning(f"board_room: dept-head '{key}' raised: {exc}")
        except FuturesTimeoutError:
            for f in future_to_key:
                f.cancel()
            logger.warning("board_room: dept-head timeout — partial responses returned")
    return responses

def _to_uuid(s: str):
    from uuid import UUID
    return UUID(s)


def _create_session_row(session_id: str, pitch: str, market: Optional[str]) -> bool:
    """Insert a pending session row into board_sessions. Non-fatal on failure.

    Schema: pitch_text, individual dept columns, no JSONB transcript.
    Passes session_id as uuid.UUID object — psycopg2 handles the type mapping.
    """
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                INSERT INTO board_sessions (
                    session_id, pitch_text, market, status, initiated_by, created_at
                ) VALUES (
                    :session_id, :pitch_text, :market, 'pending', 'ceo', NOW()
                )
                """),
                {
                    "session_id": _to_uuid(session_id),
                    "pitch_text": pitch,
                    "market": market or "",
                },
            )
        return True
    except Exception as exc:
        logger.warning(f"board_room: failed to create session row {session_id}: {exc}")
        return False


def _update_session_row(session_id: str, status: str, transcript: dict) -> bool:
    """Update session row with individual dept-head column values.

    transcript dict keys: status, responses (bd/finance/engineering/ops/legal),
    actions (list), ceo_decomposition (optional).
    Sets completed_at only on terminal states (complete/failed).
    """
    is_terminal = status in ("complete", "failed")
    responses = transcript.get("responses", {})
    ceo_extra = {
        "actions": transcript.get("actions", []),
        "ceo_decomposition": transcript.get("ceo_decomposition"),
        "error": transcript.get("error"),
    }
    ceo_synthesis = json.dumps(ceo_extra, default=str) if any(ceo_extra.values()) else None
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                UPDATE board_sessions
                SET status               = :status,
                    bd_response          = :bd,
                    finance_response     = :finance,
                    engineering_response = :engineering,
                    ops_response         = :ops,
                    legal_response       = :legal,
                    ceo_synthesis        = :ceo_synthesis,
                    completed_at         = CASE WHEN :is_terminal THEN NOW() ELSE completed_at END
                WHERE session_id = :session_id
                """),
                {
                    "session_id": _to_uuid(session_id),
                    "status": status,
                    "bd": responses.get("bd") or None,
                    "finance": responses.get("finance") or None,
                    "engineering": responses.get("engineering") or None,
                    "ops": responses.get("ops") or None,
                    "legal": responses.get("legal") or None,
                    "ceo_synthesis": ceo_synthesis,
                    "is_terminal": is_terminal,
                },
            )
        return True
    except Exception as exc:
        logger.warning(f"board_room: failed to update session row {session_id}: {exc}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def _extract_actions(dept_responses: dict, pitch: str, market: str) -> list:
    """Extract concrete actions from department responses using Cerebras 8b (LIGHT tier).
    Returns a list of action dicts or empty list on failure.
    Falls back to rule-based extraction if LLM fails.
    """

    def _try_llm():
        from litellm import completion
        from config.settings import CEREBRAS_API_KEY, CEREBRAS_BASE_URL, CEREBRAS_MODEL

        prompt = (
            "Extract 3-5 concrete actions from these board department responses. "
            "Return ONLY a JSON array, each item: {\"action\": \"...\", \"owner\": \"bd|finance|engineering|ops|legal\", \"priority\": \"high|medium|low\", \"timeline\": \"...\"}. "
            "If insufficient information, return [].\n\n"
            f"Market: {market}\nPitch: {pitch}\n"
            f"BD: {dept_responses.get('bd', '')[:500]}\n"
            f"Finance: {dept_responses.get('finance', '')[:500]}\n"
            f"Engineering: {dept_responses.get('engineering', '')[:500]}\n"
            f"Ops: {dept_responses.get('ops', '')[:500]}\n"
            f"Legal: {dept_responses.get('legal', '')[:500]}\n"
        )
        response = completion(
            model=f"openai/{CEREBRAS_MODEL}",
            api_key=CEREBRAS_API_KEY,
            base_url=CEREBRAS_BASE_URL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()
        return raw

    raw = None
    for attempt in range(2):
        try:
            raw = _try_llm()
            break
        except Exception as exc:
            err_str = str(exc)
            if "rate" in err_str.lower() or "traffic" in err_str.lower():
                time.sleep(2 ** attempt * 2)
                logger.warning(f"board_room: action extraction attempt {attempt+1} rate limited, retrying...")
                continue
            logger.warning(f"board_room: action extraction LLM failed: {exc}")
            break

    if raw:
        bracket = raw.find("[")
        if bracket >= 0:
            raw = raw[bracket:]
        close = raw.rfind("]")
        if close > 0:
            raw = raw[:close+1]
        try:
            actions = json.loads(raw)
            if isinstance(actions, list):
                cleaned = []
                for item in actions:
                    if not isinstance(item, dict):
                        continue
                    cleaned.append({
                        "owner": str(item.get("owner") or ""),
                        "action": str(item.get("action") or ""),
                        "priority": str(item.get("priority") or "medium"),
                        "timeline": str(item.get("timeline") or "TBD"),
                    })
                if cleaned:
                    return cleaned
        except Exception:
            pass

    return _fallback_actions(dept_responses)


def _fallback_actions(dept_responses: dict) -> list:
    """Rule-based action extraction from dept responses as LLM fallback."""
    actions = []
    dept_patterns = {
        "bd": ["recommend", "price", "entry", "land", "go", "target", "focus"],
        "finance": ["irr", "break-even", "margin", "debt", "equity", "funding", "cost"],
        "engineering": ["far", "bda", "bbmp", "rera", "approval", "zoning", "construction", "design"],
        "ops": ["launch", "channel", "sales", "partner", "digital", "kpi", "velocity"],
        "legal": ["title", "encumbrance", "registration", "conversion", "clearance", "compliance"],
    }
    for dept, keywords in dept_patterns.items():
        text = (dept_responses.get(dept) or "")[:3000].lower()
        matched = [kw for kw in keywords if kw in text]
        if matched:
            priority = "high" if any(kw in text for kw in ["risk", "critical", "urgent", "blocker"]) else "medium"
            actions.append({
                "owner": dept,
                "action": f"Review {dept.upper()} findings on {matched[0].replace('-', ' ')} — see response for {', '.join(matched[1:3])}",
                "priority": priority,
                "timeline": "TBD",
            })
    return actions[:5]

def _run_board_session_bg(session_id: str, pitch: str, market: str) -> None:
    """Background worker: run dept heads, extract actions, update session row to complete or failed.
    Uses a per-session provider exclusion set — never touches the global pipeline _EXCLUDED."""
    _session_excluded: set = set()
    try:
        _update_session_row(session_id, "active", {"status": "active", "responses": {}})
        decomposition = _ceo_decompose(pitch, market, _session_excluded)
        dept_responses = _run_dept_heads(pitch, market, decomposition, _session_excluded)

        # Board Room coherence self-evaluation (T-453)
        try:
            evaluator = BoardRoomEvaluator()
            flagged = evaluator.flag_low_coherence(decomposition or {}, dept_responses, threshold=0.35)
            if flagged:
                for dept_key in flagged:
                    warning = "\n\n⚠ [AUTO-FLAG: response coherence low — verify manually]"
                    if dept_key in dept_responses:
                        dept_responses[dept_key] = dept_responses[dept_key] + warning
                # Log flagged depts to agent_runs
                try:
                    with get_engine().begin() as conn:
                        conn.execute(text("""
                            INSERT INTO agent_runs
                                (agent_name, task_type, micro_market, status, metadata, started_at, completed_at)
                            VALUES
                                ('board_coherence_flag', 'board_coherence_flag', :market, 'completed',
                                 CAST(:metadata AS jsonb), NOW(), NOW())
                        """), {
                            "market": market,
                            "metadata": json.dumps({
                                "session_id": session_id,
                                "flagged_depts": flagged,
                                "market": market,
                            }),
                        })
                except Exception as log_exc:
                    logger.debug(f"[board_room] Failed to log coherence flags: {log_exc}")
        except Exception as eval_exc:
            logger.debug(f"[board_room] Coherence evaluation failed (non-blocking): {eval_exc}")

        actions = _extract_actions(dept_responses, pitch, market)
        transcript = {"status": "complete", "responses": dept_responses, "actions": actions}
        if decomposition is not None:
            transcript["ceo_decomposition"] = decomposition
        _update_session_row(session_id, "complete", transcript)
    except (ImportError, KeyError, AttributeError, TypeError) as exc:
        logger.error(f"board_room bg worker PERMANENT FAILURE for {session_id}: {exc}")
        _update_session_row(session_id, "failed", {"status": "failed", "error": f"[PERMANENT] {exc}"})
    except Exception as exc:
        logger.warning(f"board_room bg worker transient failure for {session_id}: {exc}")
        _update_session_row(session_id, "failed", {"status": "failed", "error": f"[TRANSIENT] {exc}"})


def run_board_session(pitch: str, market: str) -> dict:
    """Create a board session row, start dept-head agents in a background thread, return immediately.

    Callers poll GET /api/board/session/{session_id} for status changes:
      pending → active → complete | failed
    """
    session_id = str(uuid.uuid4())
    created = _create_session_row(session_id, pitch, market)
    if not created:
        return {
            "session_id": session_id,
            "status": "error",
            "market": market,
            "message": "DB row creation failed — check logs.",
        }
    t = threading.Thread(
        target=_run_board_session_bg,
        args=(session_id, pitch, market),
        daemon=True,
        name=f"board-{session_id[:8]}",
    )
    t.start()
    return {
        "session_id": session_id,
        "status": "pending",
        "market": market,
        "message": "Session created. Poll GET /api/board/session/{session_id} for results.",
    }


def get_board_session(session_id: str) -> Optional[dict]:
    """Fetch a board session from DB by session_id. Returns None if not found.

    Synthesises a 'transcript' dict from individual dept-head columns so the
    API response matches the shape the dashboard JS expects.
    """
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                SELECT session_id, pitch_text, market, status,
                       bd_response, finance_response, engineering_response,
                       ops_response, legal_response, ceo_synthesis,
                       created_at, completed_at
                FROM board_sessions
                WHERE session_id = :session_id
                """),
                {"session_id": _to_uuid(session_id)},
            ).mappings().fetchone()
            if row is None:
                return None

            # Build transcript dict for API/dashboard compatibility
            responses = {
                "bd": row["bd_response"],
                "finance": row["finance_response"],
                "engineering": row["engineering_response"],
                "ops": row["ops_response"],
                "legal": row["legal_response"],
            }
            ceo_extra = {}
            if row["ceo_synthesis"]:
                try:
                    ceo_extra = json.loads(row["ceo_synthesis"]) if isinstance(row["ceo_synthesis"], str) else dict(row["ceo_synthesis"])
                except Exception:
                    pass

            transcript = {
                "status": row["status"],
                "responses": {k: v for k, v in responses.items() if v},
                "actions": ceo_extra.get("actions", []),
            }
            if ceo_extra.get("ceo_decomposition"):
                transcript["ceo_decomposition"] = ceo_extra["ceo_decomposition"]
            if ceo_extra.get("error"):
                transcript["error"] = ceo_extra["error"]

            return {
                "session_id": str(row["session_id"]),
                "pitch": row["pitch_text"],
                "market": row["market"],
                "status": row["status"],
                "transcript": transcript,
                "created_at": str(row["created_at"]),
                "completed_at": str(row["completed_at"]) if row["completed_at"] else None,
            }
    except Exception as exc:
        logger.warning(f"board_room: get_board_session failed for {session_id}: {exc}")
        return None


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = run_board_session(
        pitch="Should LLS enter Yelahanka at PSF 6500?",
        market="Yelahanka",
    )
    print(json.dumps(result, indent=2))
