"""
RE_OS — RERA Developer Checker (Sprint 66 — Compounding Intelligence)
Extends rera_compliance_checker with developer_aliases table lookup.
Resolves developer names through canonical aliases for better matching.
"""

from typing import Optional
from loguru import logger

__all__ = ["resolve_developer_name", "check_developer_compliance_extended"]


def resolve_developer_name(name: str) -> tuple[str, float]:
    """Resolve a developer name through the developer_aliases table.
    Returns (canonical_name, match_confidence).

    Exact match → confidence 1.0
    Alias match → confidence 0.95
    Fuzzy match → confidence 0.8
    No match   → returns input + confidence 0.5
    """
    if not name or not name.strip():
        return ("", 0.0)

    name = name.strip()
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            # Exact match first
            row = conn.execute(
                text(
                    "SELECT canonical_name, match_confidence FROM developer_aliases WHERE alias ILIKE :n LIMIT 1"
                ),
                {"n": name},
            ).fetchone()
            if row:
                confidence = float(row[1]) if row[1] is not None else 0.95
                return (row[0], confidence)

            # Partial match
            row = conn.execute(
                text(
                    "SELECT canonical_name, match_confidence FROM developer_aliases WHERE :n ILIKE '%' || alias || '%' LIMIT 1"
                ),
                {"n": name},
            ).fetchone()
            if row:
                confidence = float(row[1]) if row[1] is not None else 0.8
                return (row[0], confidence)
    except Exception as exc:
        logger.debug("[DeveloperResolver] DB lookup failed: %s", exc)

    return (name, 0.5)


def check_developer_compliance_extended(
    developer_name: str,
    use_alias_resolution: bool = True,
) -> dict:
    """Extended developer compliance check with alias resolution.

    Args:
        developer_name: Name or alias of the developer.
        use_alias_resolution: If True, resolve through developer_aliases first.

    Returns:
        Dict with compliance results similar to rera_compliance_checker output.
    """
    from utils.rera_compliance_checker import check_developer_compliance

    resolved_name = developer_name
    match_confidence = 1.0

    if use_alias_resolution:
        resolved_name, match_confidence = resolve_developer_name(developer_name)
        logger.info(
            "[DeveloperChecker] '%s' → '%s' (conf=%.2f)",
            developer_name,
            resolved_name,
            match_confidence,
        )

    result = check_developer_compliance(resolved_name)

    return {
        "query_name": developer_name,
        "resolved_name": resolved_name,
        "match_confidence": match_confidence,
        "total_projects": result.total_projects,
        "active_projects": result.active_projects,
        "completed_projects": result.completed_projects,
        "delayed_projects": result.delayed_projects,
        "avg_delay_months": result.avg_delay_months,
        "compliance_signal": result.compliance_signal,
        "notes": result.notes,
    }
