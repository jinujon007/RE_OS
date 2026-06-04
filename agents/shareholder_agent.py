"""
RE_OS — Shareholder Agent (Sprint 66 — Compounding Intelligence)
Creates up to 4 shareholder personas from YAML spec files in agents/registry/.
Each shareholder asks one 150-char max question after a board room session.
"""
import os
from pathlib import Path
from typing import Optional
from loguru import logger
import yaml

__all__ = ["load_shareholder_specs", "create_shareholder_agent", "build_all_shareholders", "get_shareholder_questions"]

_REGISTRY_DIR = Path(__file__).parent / "registry"

_SHAREHOLDER_DEFAULTS = {
    "llm_tier": "heavy",
    "max_iter": 1,
    "allow_delegation": False,
    "verbose": False,
}


def load_shareholder_specs() -> list[dict]:
    """Load all shareholder_*.yaml files from the registry directory.
    Returns list of spec dicts, excludes non-shareholder files."""
    specs = []
    if not _REGISTRY_DIR.exists():
        logger.warning("[ShareholderAgent] Registry dir not found: %s", _REGISTRY_DIR)
        return specs
    for yaml_file in sorted(_REGISTRY_DIR.glob("shareholder_*.yaml")):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                spec = yaml.safe_load(f)
            if not spec or not spec.get("id"):
                logger.warning("[ShareholderAgent] Skipping %s: no id", yaml_file.name)
                continue
            spec["_file"] = yaml_file.name
            specs.append(spec)
            logger.info("[ShareholderAgent] Loaded shareholder: %s", spec.get("name", yaml_file.name))
        except Exception as exc:
            logger.warning("[ShareholderAgent] Error loading %s: %s", yaml_file.name, exc)
    return specs


def create_shareholder_agent(spec: dict):
    """Create a CrewAI Agent from a shareholder YAML spec.
    
    Uses HEAVY LLM (CEO tier) per Sprint 66 spec, with 150-char response max,
    designed to ask one targeted question after a board room session.
    Falls back to analysis tier if HEAVY LLM unavailable.
    """
    from crewai import Agent
    from config.llm_router import get_heavy_llm, get_analysis_llm
    
    try:
        llm = get_heavy_llm()
    except Exception:
        logger.debug("[ShareholderAgent] Heavy LLM unavailable, falling back to analysis tier")
        llm = get_analysis_llm()
    
    return Agent(
        role=spec.get("role", "Shareholder"),
        goal=spec.get("goal", f"Ask one question about {spec.get('investment_thesis', 'the deal')}"),
        backstory=spec.get("persona", ""),
        llm=llm,
        verbose=_SHAREHOLDER_DEFAULTS["verbose"],
        allow_delegation=_SHAREHOLDER_DEFAULTS["allow_delegation"],
        max_iter=_SHAREHOLDER_DEFAULTS["max_iter"],
        max_tokens=150,
    )


def build_all_shareholders() -> list:
    """Load all shareholder specs and create agents. Returns list of (spec, Agent) tuples.
    Skips specs that fail to load or create. Never raises."""
    agents = []
    specs = load_shareholder_specs()
    if not specs:
        logger.info("[ShareholderAgent] No shareholder specs found — J-2 not complete")
        return agents
    for spec in specs:
        try:
            agent = create_shareholder_agent(spec)
            agents.append((spec, agent))
            logger.info("[ShareholderAgent] Created agent: %s", spec.get("name", "?"))
        except Exception as exc:
            logger.warning("[ShareholderAgent] Failed to create agent from %s: %s", spec.get("_file", "?"), exc)
    return agents


def get_shareholder_questions(market: str, deal_summary: str) -> list[dict]:
    """Run all shareholders against a deal summary and return their questions.
    Each shareholder asks one question. Returns [{"name": ..., "question": ...}].
    Gracefully handles empty specs or LLM failures."""
    shareholders = build_all_shareholders()
    if not shareholders:
        return [{"name": "No Shareholders", "question": "Define shareholder personas first (J-2 in TASK_QUEUE.md)."}]
    
    results = []
    for spec, agent in shareholders:
        try:
            prompt = (
                f"You are {spec.get('name', 'a shareholder')}.\n"
                f"Investment thesis: {spec.get('investment_thesis', 'Growth')}\n\n"
                f"Deal summary for {market}:\n{deal_summary[:500]}\n\n"
                f"Ask exactly ONE short question (max 150 chars) that a {spec.get('name', 'shareholder')} "
                f"would ask before approving this investment."
            )
            response = agent.execute(prompt)
            question = (response or "").strip()[:150]
            results.append({
                "name": spec.get("name", "Shareholder"),
                "question": question,
                "thesis": spec.get("investment_thesis", ""),
            })
            logger.info("[ShareholderAgent] %s asks: %s", spec.get("name", "?"), question[:80])
        except Exception as exc:
            logger.warning("[ShareholderAgent] %s failed: %s", spec.get("name", "?"), exc)
            results.append({
                "name": spec.get("name", "Shareholder"),
                "question": "Unable to generate question at this time.",
                "error": str(exc),
            })
    return results
