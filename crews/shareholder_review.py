"""
RE_OS — Shareholder Board Crew (Phase 14 - Sprint 62)
Quarterly board review with 4 shareholder agents, debate round, and CEO synthesis.
"""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import text

from utils.db import get_engine
from utils.performance_digest import PerformanceDigest
from utils.decision_auditor import DecisionAuditor

try:
    from agents.shareholder_agent import load_shareholder_specs, create_shareholder_agent
except ImportError:
    load_shareholder_specs = None
    create_shareholder_agent = None

try:
    from config.llm_router import get_heavy_llm
except ImportError:
    get_heavy_llm = None

_SHAREHOLDER_TIMEOUT_S = 90


def _build_quarterly_prompt(spec: dict, quarter: str, digest_summary: str,
                            contested_count: int) -> str:
    name = spec.get("name", "Shareholder")
    role = spec.get("role", "Board Member")
    thesis = spec.get("investment_thesis", "Growth")
    persona = spec.get("persona", "")[:300]
    return (
        f"You are {name}, {role}.\n\n"
        f"Persona: {persona}\n"
        f"Investment thesis: {thesis}\n\n"
        f"QUARTERLY BOARD REVIEW — Q{quarter}\n\n"
        f"Performance summary:\n{digest_summary}\n\n"
        f"Contested decisions this quarter: {contested_count}\n\n"
        f"Your task: Review the quarter's performance and state your position.\n"
        f"Output JSON with EXACTLY these 3 fields:\n"
        f'  {{"verdict": "GO_ON_PLAN|NEEDS_CORRECTION|UNDERPERFORMING",\n'
        f'    "top_concern": "1-2 sentences on your primary concern",\n'
        f'    "recommendation": "One strategic recommendation"}}'
    )


def _build_debate_prompt(spec: dict, quarter: str,
                         opposing_verdicts: list[dict]) -> str:
    name = spec.get("name", "Shareholder")
    role = spec.get("role", "Board Member")
    opposing_text = "".join(
        f"- {v['name']} ({v['role']}): {v['verdict']} — "
        f"{v.get('top_concern', '')[:120]}\n"
        for v in opposing_verdicts
    )
    return (
        f"You are {name}, {role}.\n\n"
        f"QUARTERLY BOARD DEBATE — Q{quarter}\n\n"
        f"Other shareholders raised concerns:\n{opposing_text}\n\n"
        f"Respond to the strongest objection above. "
        f"Maintain or revise your recommendation.\n"
        f"Output JSON:\n"
        f'  {{"verdict": "GO_ON_PLAN|NEEDS_CORRECTION|UNDERPERFORMING",\n'
        f'    "response_to_objection": "Your rebuttal or concession",\n'
        f'    "final_recommendation": "Your final strategic direction"}}'
    )


def _parse_json_response(response_text: str) -> dict:
    if not response_text:
        return {}
    import re
    match = re.search(r'\{.*\}', response_text.strip(), re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _make_llm_call(spec: dict, prompt: str) -> dict:
    if create_shareholder_agent is None:
        return {
            "name": spec.get("name", "Shareholder"),
            "role": spec.get("role", ""),
            "verdict": "ABSTAIN",
            "top_concern": "Shareholder agent system unavailable (create_shareholder_agent not loaded).",
            "recommendation": "",
        }
    try:
        agent = create_shareholder_agent(spec)
        response = agent.execute(prompt)
        parsed = _parse_json_response(response)
        verdict = parsed.get("verdict", "NEEDS_CORRECTION")
        if verdict not in ("GO_ON_PLAN", "NEEDS_CORRECTION", "UNDERPERFORMING"):
            verdict = "NEEDS_CORRECTION"
        return {
            "name": spec.get("name", "Shareholder"),
            "role": spec.get("role", ""),
            "verdict": verdict,
            "top_concern": parsed.get("top_concern", ""),
            "recommendation": parsed.get("recommendation", ""),
            "response_to_objection": parsed.get("response_to_objection", ""),
        }
    except Exception as exc:
        logger.warning("[ShareholderBoard] {} failed: {}", spec.get("name", "?"), exc)
        return {
            "name": spec.get("name", "Shareholder"),
            "role": spec.get("role", ""),
            "verdict": "ABSTAIN",
            "top_concern": f"Error: {exc}",
            "recommendation": "",
        }


def _run_shareholders(specs: list[dict], prompt_factory, quarter: str,
                      digest_summary: str, contested_count: int) -> list[dict]:
    """Run all shareholders — parallel via ThreadPoolExecutor, sequential fallback."""
    if not specs:
        return _fallback_responses()
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        fut_map = {}
        for spec in specs:
            spec_prompt = prompt_factory(spec, quarter, digest_summary, contested_count)
            fut = executor.submit(_make_llm_call, spec, spec_prompt)
            fut_map[fut] = spec
        for future in as_completed(fut_map, timeout=_SHAREHOLDER_TIMEOUT_S):
            spec = fut_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                logger.warning("[ShareholderBoard] {} timed out: {}", spec.get("name", "?"), exc)
                results.append({
                    "name": spec.get("name", "Shareholder"),
                    "role": spec.get("role", ""),
                    "verdict": "ABSTAIN",
                    "top_concern": "Shareholder did not respond in time.",
                    "recommendation": "",
                })
    return results


def _needs_debate(responses: list[dict]) -> bool:
    concerning_count = sum(
        1 for r in responses
        if r.get("verdict") in ("NEEDS_CORRECTION", "UNDERPERFORMING")
    )
    return concerning_count >= 2


def _generate_ceo_synthesis(quarter: str, digest: dict,
                            decisions: list[dict],
                            shareholder_responses: list[dict],
                            debate_triggered: bool,
                            debate_round: list[dict] | None = None) -> dict:
    digest_summary = json.dumps(digest, indent=2, default=str)[:1000]
    llm_prompt = (
        f"You are the CEO of LLS (Land and LifeSpace). Quarterly board review — Q{quarter}.\n\n"
        f"Performance digest:\n{digest_summary}\n\n"
        f"Decisions: {len(decisions)} reviewed\n"
        f"Debate triggered: {debate_triggered}\n\n"
        f"Shareholder responses:\n"
    )
    for r in shareholder_responses:
        llm_prompt += (
            f"- {r.get('name')} ({r.get('role')}): "
            f"{r.get('verdict')} — {r.get('top_concern', '')[:100]}\n"
        )
    if debate_round:
        llm_prompt += "\nDebate round:\n"
        for r in debate_round:
            llm_prompt += f"- {r.get('name')}: {r.get('response_to_objection', '')[:150]}\n"

    llm_prompt += (
        "\nOutput JSON:\n"
        '  {"quarter_verdict": "GO_ON_PLAN|NEEDS_CORRECTION|UNDERPERFORMING",\n'
        '   "key_theme": "Single sentence on the most important strategic theme",\n'
        '   "strategic_direction": "2-3 sentences on where we go next",\n'
        '   "ceo_letter_text": "400-600 word CEO letter to shareholders"}'
    )

    try:
        if get_heavy_llm:
            from crewai import Agent
            ceo_agent = Agent(
                role="CEO, LLS",
                goal="Synthesize quarterly board discussion into strategic CEO letter",
                backstory="Founder-CEO with 16 years in Bengaluru real estate",
                llm=get_heavy_llm(),
                max_tokens=800,
            )
            response = ceo_agent.execute(llm_prompt)
            parsed = _parse_json_response(response)
            if parsed.get("ceo_letter_text"):
                return parsed
    except Exception as exc:
        logger.warning("[ShareholderBoard] CEO LLM synthesis failed: {}", exc)

    return _fallback_ceo_synthesis(quarter, shareholder_responses, debate_triggered)


def _fallback_ceo_synthesis(quarter: str,
                            responses: list[dict],
                            debate_triggered: bool) -> dict:
    verdicts = [r.get("verdict", "ABSTAIN") for r in responses]
    go = verdicts.count("GO_ON_PLAN")
    needs = verdicts.count("NEEDS_CORRECTION")
    under = verdicts.count("UNDERPERFORMING")

    if go > needs + under:
        quarter_verdict = "GO_ON_PLAN"
    elif under >= go:
        quarter_verdict = "UNDERPERFORMING"
    else:
        quarter_verdict = "NEEDS_CORRECTION"

    themes = [r.get("top_concern", "") for r in responses if r.get("top_concern")]
    key_theme = themes[0][:200] if themes else "No clear theme identified."

    concern_lines = ""
    for r in responses:
        if r.get("top_concern"):
            concern_lines += f"- {r.get('name')}: {r.get('top_concern')[:150]}\n"

    debate_note = (
        "A debate was triggered as multiple shareholders raised "
        "significant concerns about our trajectory. "
        if debate_triggered else ""
    )

    letter = (
        f"Q{quarter} Shareholder Letter\n\n"
        f"Dear Shareholders,\n\n"
        f"This quarter our board reviewed {len(responses)} strategic perspectives. "
        f"The collective verdict is: {quarter_verdict}.\n\n"
        f"{debate_note}"
        f"Key areas of focus identified this quarter:\n"
        f"{concern_lines}"
        f"\nLooking ahead, our strategic direction is to address these "
        f"concerns while maintaining our commitment to identifying and "
        f"executing high-quality land acquisitions in North Bengaluru.\n\n"
        f"The Board will reconvene next quarter.\n\n"
        f"Regards,\nCEO, LLS"
    )

    return {
        "quarter_verdict": quarter_verdict,
        "key_theme": key_theme,
        "strategic_direction": "Address shareholder concerns while pursuing identified opportunities.",
        "ceo_letter_text": letter,
    }


def _save_session(quarter: str, session_data: dict) -> str:
    session_id = str(uuid.uuid4())
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO shareholder_sessions
                    (id, session_type, quarter, status, shareholder_responses,
                     debate_transcript, ceo_synthesis, verdict, completed_at)
                    VALUES (:id, 'quarterly_board', :quarter, 'complete',
                            CAST(:responses AS jsonb), :transcript,
                            :synthesis, :verdict, NOW())
                """),
                {
                    "id": session_id,
                    "quarter": quarter,
                    "responses": json.dumps(session_data.get("shareholder_responses", [])),
                    "transcript": session_data.get("debate_transcript", ""),
                    "synthesis": session_data.get("ceo_synthesis", ""),
                    "verdict": session_data.get("quarter_verdict", ""),
                },
            )
        logger.info("[ShareholderBoard] Session saved: {}", session_id)
    except Exception as exc:
        logger.warning("[ShareholderBoard] Failed to save session: {}", exc)
    return session_id


class ShareholderBoardCrew:
    """Quarterly board review crew. Runs 4 shareholders, debate, CEO synthesis."""

    @staticmethod
    def run_quarterly_review(quarter: str) -> dict:
        digest = PerformanceDigest.build(quarter)
        decisions = DecisionAuditor.audit_quarter(quarter)
        contested_count = len([d for d in decisions if _is_contested(d)])

        digest_summary = (
            f"Deals evaluated: {digest.get('deal_metrics', {}).get('deal_count', 0)}, "
            f"Avg IRR: {digest.get('deal_metrics', {}).get('avg_irr_pct', 'N/A')}%\n"
            f"New projects tracked: {sum(p.get('project_count', 0) for p in digest.get('new_projects', []))}\n"
            f"Avg absorption: {digest.get('absorption_trend', {}).get('avg_absorption_pct', 'N/A')}%\n"
            f"Over-budget token runs: {digest.get('token_efficiency', {}).get('over_budget_count', 0)}"
        )

        specs = load_shareholder_specs() if load_shareholder_specs else []
        if not specs:
            logger.warning("[ShareholderBoard] No shareholder specs found — using placeholders")

        shareholder_responses = _run_shareholders(
            specs, _build_quarterly_prompt, quarter,
            digest_summary, contested_count,
        ) if specs else _fallback_responses()

        debate_triggered = _needs_debate(shareholder_responses)
        debate_round = None
        if debate_triggered and specs:
            opposing = [r for r in shareholder_responses
                        if r.get("verdict") in ("NEEDS_CORRECTION", "UNDERPERFORMING")]
            debate_round = []
            for spec in specs:
                debate_prompt = _build_debate_prompt(spec, quarter, opposing)
                debate_round.append(_make_llm_call(spec, debate_prompt))

        synthesis = _generate_ceo_synthesis(
            quarter, digest, decisions,
            shareholder_responses, debate_triggered, debate_round,
        )

        result = {
            "quarter": quarter,
            "digest": digest,
            "contested_decisions": contested_count,
            "shareholder_responses": shareholder_responses,
            "debate_triggered": debate_triggered,
            "debate_round": debate_round,
            "quarter_verdict": synthesis.get("quarter_verdict", ""),
            "key_theme": synthesis.get("key_theme", ""),
            "strategic_direction": synthesis.get("strategic_direction", ""),
            "ceo_letter_text": synthesis.get("ceo_letter_text", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        session_id = _save_session(quarter, result)
        result["session_id"] = session_id
        return result

    @staticmethod
    def save_letter(session_id: str, letter_text: str, quarter: str = "") -> str:
        """Save CEO letter to output file with frontmatter."""
        output_dir = Path("outputs/shareholder_letters")
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"Q{quarter.replace('Q', '')}" if quarter else session_id[:8]
        filename = f"{prefix}_CEO_Letter.md"
        path = output_dir / filename

        frontmatter = (
            f"---\n"
            f"date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
            f"session_id: {session_id}\n"
            f"quarter: {quarter}\n"
            f"---\n\n"
        )
        path.write_text(frontmatter + letter_text, encoding="utf-8")
        logger.info("[ShareholderBoard] Letter saved: {}", path)
        return str(path)


def _is_contested(decision: dict) -> bool:
    sv = decision.get("shareholder_verdicts")
    if sv and isinstance(sv, list) and len(sv) >= 2:
        has_go = any(v.get("verdict") == "GO" for v in sv)
        has_nogo = any(v.get("verdict") == "NO-GO" for v in sv)
        return has_go and has_nogo
    return False


def _fallback_responses() -> list[dict]:
    return [
        {"name": "Arjun Menon", "role": "Demand & Timing Shareholder",
         "verdict": "GO_ON_PLAN", "top_concern": "Demand absorption appears healthy.",
         "recommendation": "Continue current acquisition pace."},
        {"name": "Rajan Pillai", "role": "Legal & Regulatory Risk Shareholder",
         "verdict": "GO_ON_PLAN", "top_concern": "No major compliance flags.",
         "recommendation": "Maintain legal diligence standard."},
        {"name": "Maya Krishnan", "role": "Legacy & Community Shareholder",
         "verdict": "NEEDS_CORRECTION", "top_concern": "Community engagement needs improvement.",
         "recommendation": "Allocate budget for local stakeholder outreach."},
        {"name": "Vikram Shah", "role": "Financial Maximizer Shareholder",
         "verdict": "GO_ON_PLAN", "top_concern": "IRR projections consistent with targets.",
         "recommendation": "Focus on higher-margin JD deals."},
    ]
