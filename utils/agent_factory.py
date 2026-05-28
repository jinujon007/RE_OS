"""
Utility to create CrewAI agents based on role, tier, and market.
The schema (T-275) defines:
- role: identifier matching an agent module (ceo, analyst, scraper, parser, sentinel)
- tier: one of "heavy", "analysis", "light"
- market: optional string passed to the agent (currently unused but kept for future extensions)
"""

import importlib
from typing import Any

# Mapping of role name to its factory function within the agents package
_AGENT_FACTORIES = {
    "ceo": "agents.ceo_agent.create_ceo_agent",
    "analyst": "agents.analyst_agent.create_analyst_agent",
    "scraper": "agents.scraper_agent.create_scraper_agent",
    "parser": "agents.parser_agent.create_parser_agent",
    "sentinel": "agents.sentinel_agent.create_sentinel_agent",
    "bd": "agents.board_room.bd_head.build_bd_head_agent",
    "finance": "agents.board_room.finance_head.build_finance_head_agent",
    "engineering": "agents.board_room.engineering_head.build_engineering_head_agent",
    "ops": "agents.board_room.ops_head.build_ops_head_agent",
}

# Tier‑to‑LLM router helpers (already expose appropriate LLMs)
_TIER_ROUTER = {
    "heavy": "config.llm_router.get_heavy_llm",
    "analysis": "config.llm_router.get_analysis_llm",
    "light": "config.llm_router.get_light_llm",
}

def _load_callable(path: str) -> Any:
    module_path, attr = path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, attr)

def create_agent(role: str, tier: str, market: str = ""):
    """Factory entry point.
    Args:
        role: logical role name (e.g., "ceo", "analyst").
        tier: LLM tier – "heavy", "analysis", or "light".
        market: optional market identifier – currently injected into the agent's backstory if needed.
    Returns:
        crewai.Agent instance configured with the appropriate LLM and tools.
    """
    role_key = role.lower()
    tier_key = tier.lower()

    if role_key not in _AGENT_FACTORIES:
        raise ValueError(f"Unknown agent role '{role}'. Available: {list(_AGENT_FACTORIES)}")
    if tier_key not in _TIER_ROUTER:
        raise ValueError(f"Unknown tier '{tier}'. Choose from heavy, analysis, light")

    # Load the specific agent creator and instantiate
    creator = _load_callable(_AGENT_FACTORIES[role_key])
    agent = creator()

    # Override LLM based on requested tier (allows runtime routing flexibility)
    llm_getter = _load_callable(_TIER_ROUTER[tier_key])
    agent.llm = llm_getter()

    # Optionally enrich backstory with market context
    if market:
        agent.backstory = f"{agent.backstory}\n\nOperating in market: {market}."

    return agent
