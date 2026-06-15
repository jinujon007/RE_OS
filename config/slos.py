"""
Data Quality Service Level Objectives (SLOs) — operational targets.
These are NOT gate pass/fail criteria. They define acceptable freshness windows
for each data source. Used by DataQualityMonitor and /api/health for alerting.

Sources are classified by refresh cadence:
  - HIGH FREQUENCY: News, Listings (daily)
  - MEDIUM FREQUENCY: RERA, IGR (weekly)
  - LOW FREQUENCY: Kaveri, Developer profiles (bi-weekly)

SLO breaches should trigger Discord #ops alerts, NOT pipeline blocks.
"""

from dataclasses import dataclass, field
from datetime import timedelta


@dataclass(frozen=True)
class SourceSLO:
    name: str
    max_age_hours: int
    severity: str = "warning"  # warning | critical
    description: str = ""


_SLOS: list[SourceSLO] = [
    SourceSLO("news_scout", 24, "warning", "News articles should be scraped daily"),
    SourceSLO("portal_plugin", 168, "warning", "Listings should be refreshed weekly"),
    SourceSLO(
        "rera_karnataka",
        48,
        "critical",
        "RERA project data refreshed via ingest engine",
    ),
    SourceSLO(
        "igr_karnataka", 48, "warning", "IGR transaction data from portal or gazette"
    ),
    SourceSLO(
        "kaveri_bhoomi",
        168,
        "warning",
        "Kaveri/Bhoomi guidance values refreshed weekly",
    ),
    SourceSLO("developer_plugin", 336, "low", "Developer profiles change slowly"),
    SourceSLO(
        "distressed_plugin", 168, "low", "Distressed/auction data refreshed weekly"
    ),
    SourceSLO("bbmp_plugin", 336, "low", "BBMP Khata data changes slowly"),
]

SLO_MAP: dict[str, SourceSLO] = {slo.name: slo for slo in _SLOS}


def check_slo(plugin_id: str, hours_since_update: float) -> tuple[bool, str]:
    """Check if a source meets its SLO target.

    Returns (passes_slo, message) where passes_slo is True if
    hours_since_update <= slo.max_age_hours.
    """
    slo = SLO_MAP.get(plugin_id)
    if slo is None:
        return True, f"No SLO defined for {plugin_id}"
    if hours_since_update <= slo.max_age_hours:
        return (
            True,
            f"{plugin_id}: {hours_since_update:.0f}h <= {slo.max_age_hours}h SLO",
        )
    return (
        False,
        f"{plugin_id}: {hours_since_update:.0f}h > {slo.max_age_hours}h SLO ({slo.severity})",
    )


def all_slo_status(freshness: dict[str, dict]) -> dict:
    """Evaluate all SLO statuses against a freshness dict.

    freshness should be in format returned by DataQualityMonitor.freshness_score():
        {"source": {"hours_since_update": ..., "status": ...}}

    Returns {"passing": int, "failing": int, "details": {...}}
    """
    passing = 0
    failing = 0
    details = {}
    for plugin_id, info in freshness.items():
        hours = info.get("hours_since_update")
        if hours is None:
            details[plugin_id] = {"passes_slo": False, "message": "no data"}
            failing += 1
            continue
        passes, message = check_slo(plugin_id, float(hours))
        details[plugin_id] = {"passes_slo": passes, "message": message}
        if passes:
            passing += 1
        else:
            failing += 1
    return {"slo_pass": passing, "slo_fail": failing, "details": details}
