"""
RE_OS — Compliance Researcher Agent (Phase 12 — Legal Department)
Standalone researcher for RERA compliance, zone risk, and encumbrance checks.
Reports to Legal Head Agent. Uses all three legal tools.
"""

from crewai import Agent
from config.llm_router import get_analysis_llm
from crewai.tools import BaseTool
import json
from utils.rera_compliance_checker import check_developer_compliance
from utils.zone_risk_checker import check_zone_risk
from utils.kaveri_encumbrance import check_encumbrance

# ── Tool wrappers (avoid import dependency on legal_head.py) ──


class _RERAComplianceTool(BaseTool):
    name: str = "rera_compliance_check"
    description: str = "Check developer's RERA compliance from DB. Input: JSON with 'developer_name', optional 'market'."

    def _run(self, input_str: str) -> str:
        try:
            p = json.loads(input_str)
        except Exception:
            return json.dumps({"error": "invalid JSON"})
        try:
            r = check_developer_compliance(
                p.get("developer_name", ""), market=p.get("market")
            )
            return json.dumps(
                {k: v for k, v in r.__dict__.items() if k != "inactive_anomalies"},
                indent=2,
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})


class _ZoneRiskTool(BaseTool):
    name: str = "zone_risk_check"
    description: str = "Check zone rules + overlays for a market. Input: JSON with 'market', optional 'zone' (default R2)."

    def _run(self, input_str: str) -> str:
        try:
            p = json.loads(input_str)
        except Exception:
            return json.dumps({"error": "invalid JSON"})
        try:
            r = check_zone_risk(p.get("market", ""), p.get("zone", "R2"))
            return json.dumps(
                {k: v for k, v in r.__dict__.items()}, indent=2, default=str
            )
        except Exception as e:
            return json.dumps({"error": str(e)})


class _EncumbranceCheckTool(BaseTool):
    name: str = "encumbrance_check"
    description: str = (
        "Check encumbrance via Kaveri. Input: JSON with 'market', optional 'survey_no'."
    )

    def _run(self, input_str: str) -> str:
        try:
            p = json.loads(input_str)
        except Exception:
            return json.dumps({"error": "invalid JSON"})
        try:
            r = check_encumbrance(p.get("market", ""), survey_no=p.get("survey_no"))
            return json.dumps(
                {k: v for k, v in r.__dict__.items()}, indent=2, default=str
            )
        except Exception as e:
            return json.dumps({"error": str(e)})


def create_compliance_researcher_agent(market: str | None = None) -> Agent:
    return Agent(
        role="Compliance Researcher — Legal Division",
        goal=(
            f"Run data-grounded compliance checks for {market if market else 'any market'}: "
            "RERA developer track record, zone regulatory risk, and encumbrance status from Kaveri data. "
            "Return structured findings the Legal Head can act on."
        ),
        backstory=(
            "Detail-oriented legal researcher specialising in Karnataka real estate regulations. "
            f"{'Focusing on ' + market + '.' if market else ''} "
            "Pulls directly from RERA Karnataka DB, Kaveri registration data, and BDA zone rules "
            "— never guesses. "
            "Flags every unresolved legal item with the specific Karnataka statute or regulatory body. "
            "Output is a structured checklist: item, status, authority, recommended action."
        ),
        tools=[_RERAComplianceTool(), _ZoneRiskTool(), _EncumbranceCheckTool()],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )


if __name__ == "__main__":
    agent = create_compliance_researcher_agent()
    print(f"Compliance Researcher created: {agent.role}")
    print(f"Tools: {[t.name for t in agent.tools]}")

    # Smoke test each tool independently
    test_cases = [
        ("rera_compliance_check", '{"developer_name": "Brigade"}'),
        ("zone_risk_check", '{"market": "Yelahanka", "zone": "R2"}'),
        ("encumbrance_check", '{"market": "Yelahanka"}'),
    ]
    for tool_name, test_input in test_cases:
        tool = next((t for t in agent.tools if t.name == tool_name), None)
        if tool:
            result = tool._run(test_input)
            print(f"\n  [{tool_name}] -> {result[:200]}...")
        else:
            print(f"\n  [{tool_name}] -> NOT FOUND")
