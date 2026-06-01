"""
RE_OS — Compliance Researcher Agent (Phase 12 — Legal Department)
Standalone researcher for RERA compliance, zone risk, and encumbrance checks.
Reports to Legal Head Agent. Uses all three legal tools.
"""
from crewai import Agent
from config.llm_router import get_analysis_llm
from agents.board_room.legal_head import RERAComplianceTool, ZoneRiskTool, EncumbranceCheckTool


def create_compliance_researcher_agent() -> Agent:
    return Agent(
        role="Compliance Researcher — Legal Division",
        goal=(
            "Run data-grounded compliance checks: RERA developer track record, "
            "zone regulatory risk, and encumbrance status from Kaveri data. "
            "Return structured findings the Legal Head can act on."
        ),
        backstory=(
            "Detail-oriented legal researcher specialising in Karnataka real estate regulations. "
            "Pulls directly from RERA Karnataka DB, Kaveri registration data, and BDA zone rules "
            "— never guesses. "
            "Flags every unresolved legal item with the specific Karnataka statute or regulatory body. "
            "Output is a structured checklist: item, status, authority, recommended action."
        ),
        tools=[RERAComplianceTool(), ZoneRiskTool(), EncumbranceCheckTool()],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=3,
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
