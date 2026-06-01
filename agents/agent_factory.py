"""
RE_OS — Agent Factory (Phase 8 — Agent Hiring & Onboarding)

Loads agent spec YAML files from agents/registry/ and instantiates CrewAI Agents.
Syncs the registry to the agent_registry DB table on container startup.

Design principles:
  - Defensive: every failure mode caught and logged, never crashes the pipeline
  - Observable: structured logging with component prefix for log aggregation
  - Testable: pure functions with explicit inputs, no hidden state surprises
  - Extensible: tool registry is lazily built and import-error tolerant

Usage:
    >>> from agents.agent_factory import scan_registry, build_agent_from_spec
    >>> specs = scan_registry()
    >>> agent = build_agent_from_spec(specs[0])

    >>> from agents.agent_factory import sync_registry_to_db
    >>> sync_registry_to_db()  # startup sync
"""
from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

from loguru import logger

_REGISTRY_DIR: Path = Path(__file__).resolve().parent / "registry"
_MAX_SPEC_BYTES: int = 1_048_576

_VALID_MARKETS: frozenset[str] = frozenset({"Yelahanka", "Devanahalli", "Hebbal"})
_VALID_LLM_TIERS: frozenset[str] = frozenset({"heavy", "analysis", "light"})
_VALID_DEPARTMENTS: frozenset[str] = frozenset({
    "bd", "engineering", "finance", "legal", "ops", "process", "scout", "board",
})
_REQUIRED_SPEC_FIELDS: tuple[str, ...] = ("id", "name", "role", "persona", "llm_tier")

_TOOL_REGISTRY: dict[str, type] = {}


def _get_tool_registry() -> dict[str, type]:
    """Lazily build tool name → class map.

    Imported once and cached. Gracefully handles missing tool modules —
    partial registry is better than no registry.
    """
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY:
        return _TOOL_REGISTRY
    try:
        from agents.analyst_agent import (
            MarketSummaryTool, CompetitorAnalysisTool,
            DistressedDeveloperListTool, ReportGeneratorTool,
            FeasibilityTool, FeasibilityAnalystTool, IntelSearchTool,
        )
        from agents.architect_agent import FSICalculatorTool, TypologyRecommenderTool, GreenCoverageTool
        from agents.board_room.legal_head import (
            RERAComplianceTool, ZoneRiskTool, EncumbranceCheckTool,
        )
        _TOOL_REGISTRY = {
            "MarketSummaryTool": MarketSummaryTool,
            "CompetitorAnalysisTool": CompetitorAnalysisTool,
            "DistressedDeveloperListTool": DistressedDeveloperListTool,
            "ReportGeneratorTool": ReportGeneratorTool,
            "FeasibilityTool": FeasibilityTool,
            "FeasibilityAnalystTool": FeasibilityAnalystTool,
            "IntelSearchTool": IntelSearchTool,
            "FSICalculatorTool": FSICalculatorTool,
            "TypologyRecommenderTool": TypologyRecommenderTool,
            "GreenCoverageTool": GreenCoverageTool,
            "RERAComplianceTool": RERAComplianceTool,
            "ZoneRiskTool": ZoneRiskTool,
            "EncumbranceCheckTool": EncumbranceCheckTool,
        }
    except Exception as exc:
        logger.opt(exception=True).warning(
            "[AgentFactory] Tool registry partially loaded: {exc}", exc=exc,
        )
    return _TOOL_REGISTRY


# ── Spec loading & validation ───────────────────────────────────────────────


def load_spec(yaml_path: Path) -> dict[str, Any]:
    """Load and validate a single YAML agent spec file.

    Args:
        yaml_path: Path to the .yaml spec file.

    Returns:
        Parsed and validated spec dictionary.

    Raises:
        ValueError: If required fields are missing, types are wrong,
                    or llm_tier is not in the allowed set.
        FileNotFoundError: If yaml_path does not exist (from open()).
        yaml.YAMLError: If the YAML content is malformed.
    """
    import yaml

    with open(yaml_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError(f"Agent spec {yaml_path.name} is empty")

    if not isinstance(raw, dict):
        raise ValueError(
            f"Agent spec {yaml_path.name} must be a dict, got {type(raw).__name__}"
        )

    spec: dict[str, Any] = raw

    for field in _REQUIRED_SPEC_FIELDS:
        if not spec.get(field):
            raise ValueError(
                f"Agent spec {yaml_path.name} missing required field: '{field}'"
            )
        if not isinstance(spec[field], str):
            raise ValueError(
                f"Agent spec {yaml_path.name}: '{field}' must be a string, "
                f"got {type(spec[field]).__name__}"
            )

    tier = spec["llm_tier"]
    if tier not in _VALID_LLM_TIERS:
        raise ValueError(
            f"Invalid llm_tier '{tier}' in {yaml_path.name}. "
            f"Must be one of: {', '.join(sorted(_VALID_LLM_TIERS))}"
        )

    dept = spec.get("department")
    if dept is not None and dept not in _VALID_DEPARTMENTS:
        logger.warning(
            "[AgentFactory] Unknown department '{dept}' in {name} — "
            "valid departments: {valid}",
            dept=dept, name=yaml_path.name, valid=", ".join(sorted(_VALID_DEPARTMENTS)),
        )

    markets = spec.get("markets")
    if markets is not None:
        if not isinstance(markets, list):
            raise ValueError(
                f"Agent spec {yaml_path.name}: 'markets' must be a list, "
                f"got {type(markets).__name__}"
            )
        for m in markets:
            if not isinstance(m, str):
                raise ValueError(
                    f"Agent spec {yaml_path.name}: each market must be a string, "
                    f"got {type(m).__name__}"
                )
            if m not in _VALID_MARKETS:
                logger.warning(
                    "[AgentFactory] Unknown market '{market}' in {name}. "
                    "Known markets: {known}",
                    market=m, name=yaml_path.name, known=", ".join(sorted(_VALID_MARKETS)),
                )

    tools = spec.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            raise ValueError(
                f"Agent spec {yaml_path.name}: 'tools' must be a list, "
                f"got {type(tools).__name__}"
            )

    return spec


# ── Agent construction ──────────────────────────────────────────────────────


def build_agent_from_spec(spec: dict[str, Any]):
    """Instantiate a CrewAI Agent from a validated spec dictionary.

    Resolves llm_tier → LLM provider, tool names → tool instances,
    and injects memory_context into the Agent's backstory.

    Args:
        spec: Validated agent spec dictionary (from load_spec).

    Returns:
        crewai.Agent instance configured per the spec.

    Raises:
        ImportError: If crewai is not installed (unusual — it is a project dep).
    """
    from crewai import Agent
    from config.llm_router import get_heavy_llm, get_analysis_llm, get_light_llm

    tier = spec.get("llm_tier", "analysis")
    llm_fn = {
        "heavy": get_heavy_llm,
        "analysis": get_analysis_llm,
        "light": get_light_llm,
    }.get(tier, get_analysis_llm)
    llm = llm_fn()

    tool_registry = _get_tool_registry()
    tools = []
    for tool_name in (spec.get("tools") or []):
        tool_cls = tool_registry.get(tool_name)
        if tool_cls:
            tools.append(tool_cls())
        else:
            logger.warning(
                "[AgentFactory] Unknown tool '{tool}' in spec '{id}' — skipped",
                tool=tool_name, id=spec.get("id", "?"),
            )

    backstory = spec["persona"]
    memory_ctx = spec.get("memory_context", "")
    if memory_ctx:
        backstory = f"{backstory.rstrip()}\n\nFOCUS MARKET: {memory_ctx.upper()}"
    markets = spec.get("markets") or []
    if markets and not memory_ctx:
        backstory = f"{backstory.rstrip()}\n\nFOCUS MARKETS: {', '.join(str(m) for m in markets)}"

    return Agent(
        role=spec["role"],
        goal=spec.get("goal", spec["role"]),
        backstory=backstory,
        tools=tools,
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=int(spec.get("max_iter", 3)),
    )


# ── Registry scanning ───────────────────────────────────────────────────────


def scan_registry(registry_dir: Path | None = None) -> list[dict[str, Any]]:
    """Scan registry directory and return all valid spec dicts.

    Excludes files starting with underscore (_schema.yaml, etc.).
    Invalid specs are logged as warnings and skipped — never crash.

    Args:
        registry_dir: Path to registry directory. Defaults to agents/registry/.

    Returns:
        List of validated spec dictionaries. Empty list if dir missing or empty.
    """
    target = registry_dir or _REGISTRY_DIR
    if not target.exists():
        logger.debug("[AgentFactory] Registry directory not found: {path}", path=target)
        return []
    if not target.is_dir():
        logger.warning("[AgentFactory] Registry path is not a directory: {path}", path=target)
        return []

    specs: list[dict[str, Any]] = []
    for yaml_file in sorted(target.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        try:
            specs.append(load_spec(yaml_file))
            logger.debug("[AgentFactory] Loaded spec: {name}", name=yaml_file.name)
        except Exception as exc:
            logger.opt(exception=True).warning(
                "[AgentFactory] Skipping {name}: {exc}",
                name=yaml_file.name, exc=exc,
            )

    return specs


# ── DB sync ─────────────────────────────────────────────────────────────────


def sync_registry_to_db(registry_dir: Path | None = None) -> int:
    """Upsert all registry YAML specs into the agent_registry DB table.

    Idempotent — safe to call on every container start. Uses ON CONFLICT
    to update existing rows without error.

    Args:
        registry_dir: Path to registry directory. Defaults to agents/registry/.

    Returns:
        Number of specs successfully upserted. 0 if registry empty or DB error.
    """
    from sqlalchemy import text
    from utils.db import get_engine

    specs = scan_registry(registry_dir)
    if not specs:
        logger.info("[AgentFactory] No registry specs to sync")
        return 0

    synced = 0
    try:
        with get_engine().begin() as conn:
            for spec in specs:
                conn.execute(
                    text("""
                        INSERT INTO agent_registry
                            (id, name, role, department, spec, llm_tier, active, hired_on)
                        VALUES
                            (:id, :name, :role, :dept, :spec::jsonb, :tier, :active, NOW())
                        ON CONFLICT (id) DO UPDATE SET
                            name       = EXCLUDED.name,
                            role       = EXCLUDED.role,
                            department = EXCLUDED.department,
                            spec       = EXCLUDED.spec,
                            llm_tier   = EXCLUDED.llm_tier,
                            active     = EXCLUDED.active
                    """),
                    {
                        "id": spec["id"],
                        "name": spec["name"],
                        "role": spec["role"],
                        "dept": spec.get("department"),
                        "spec": _json.dumps(spec, default=str),
                        "tier": spec["llm_tier"],
                        "active": spec.get("active", True),
                    },
                )
                synced += 1
    except Exception as exc:
        logger.opt(exception=True).error(
            "[AgentFactory] DB sync failed after {count} records: {exc}",
            count=synced, exc=exc,
        )
        return synced

    logger.info(
        "[AgentFactory] Synced {count} agent(s) to registry",
        count=synced,
    )
    return synced


# ── Convenience API (for T-415 POST endpoint) ───────────────────────────────


def create_agent_from_yaml(yaml_content: str) -> dict[str, Any]:
    """Parse a YAML string and return a validated spec dict.

    Intended for the T-415 POST /api/registry endpoint where a new
    agent spec is submitted as a YAML string from the dashboard form.

    Args:
        yaml_content: Raw YAML string.

    Returns:
        Validated spec dictionary.

    Raises:
        ValueError: If the YAML is invalid, empty, or fails validation.
    """
    import yaml
    raw = yaml.safe_load(yaml_content)
    if raw is None:
        raise ValueError("Empty YAML content — no agent spec provided")
    if not isinstance(raw, dict):
        raise ValueError(f"YAML must define a mapping (dict), got {type(raw).__name__}")
    spec: dict[str, Any] = raw
    required = ("id", "name", "role", "persona", "llm_tier")
    for field in required:
        if not spec.get(field):
            raise ValueError(f"Missing required field: '{field}'")
        if not isinstance(spec[field], str):
            raise ValueError(f"Field '{field}' must be a string, got {type(spec[field]).__name__}")
    tier = spec["llm_tier"]
    if tier not in _VALID_LLM_TIERS:
        raise ValueError(
            f"llm_tier must be one of: {', '.join(sorted(_VALID_LLM_TIERS))}, got '{tier}'"
        )
    return spec


# ── Standalone test ─────────────────────────────────────────────────────────


if __name__ == "__main__":
    import sys

    specs = scan_registry()
    if not specs:
        print("[AgentFactory] No specs found in registry directory.", file=sys.stderr)
        sys.exit(1)

    print(f"[AgentFactory] Found {len(specs)} agent spec(s) in registry:\n")
    for s in specs:
        print(f"  📋 {s['id']:35s} | {s['name']:20s} | tier={s['llm_tier']:9s} | ", end="")
        markets = s.get("markets", [])
        print(f"markets={markets}" if markets else "no markets")

    print("\n[AgentFactory] Building agents...")
    for s in specs:
        try:
            agent = build_agent_from_spec(s)
            print(f"  ✅ {s['id']:35s} → Agent(role={agent.role!r}, tools={len(agent.tools)}, max_iter={agent.max_iter})")
        except Exception as exc:
            print(f"  ❌ {s['id']:35s} → FAILED: {exc}")

    print(f"\n[AgentFactory] Syncing {len(specs)} spec(s) to DB...")
    count = sync_registry_to_db()
    print(f"[AgentFactory] DB sync: {count} record(s) upserted.")

    print("\n[AgentFactory] All checks complete.")
