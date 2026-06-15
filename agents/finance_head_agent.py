"""
RE_OS -- Finance Head Agent (Phase 6 -- Finance Department)
Standalone feasibility analyst for LLS land acquisition decisions.
Uses LLS standard model: ₹2,200/sqft construction, 20% IRR threshold, 60:40 equity:debt.
"""

from crewai import Agent
from config.llm_router import get_analysis_llm
from agents.analyst_agent import FeasibilityAnalystTool, FeasibilityTool


def create_finance_head_agent() -> Agent:
    return Agent(
        role="VP -- Finance & Capital Strategy",
        goal=(
            "Evaluate land acquisition feasibility using the LLS standard model. "
            "Produce a one-page financial verdict: land cost, GDV, base/bull/bear IRR, "
            "equity requirement, and a GO / MARGINAL / NO-GO recommendation."
        ),
        backstory=(
            "Conservative capital allocator with 12 years in Bengaluru real estate finance. "
            "Uses the LLS standard model: ₹2,200/sqft hard construction cost, 20% IRR threshold "
            "for a GO, 60:40 equity:debt. Builds three scenarios for every deal -- base, bull (+10% PSF), "
            "bear (-10% PSF) -- and makes the GO/NO-GO call on the bear case, not the base. "
            "Never accepts a deal where the bear case IRR falls below 12%. "
            "Always asks: what is the downside, and can LLS survive it?"
        ),
        tools=[FeasibilityAnalystTool(), FeasibilityTool()],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


if __name__ == "__main__":
    agent = create_finance_head_agent()
    print(f"Finance Head Agent created: {agent.role}")
    print(f"Tools: {[t.name for t in agent.tools]}")
