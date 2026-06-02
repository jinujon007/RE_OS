"""Shared Prometheus metrics for RE_OS runtime hooks."""

from prometheus_client import Counter, Histogram


pipeline_runs_total = Counter(
    "pipeline_runs_total",
    "Total number of pipeline runs",
    ["market"],
)

llm_calls_total = Counter(
    "llm_calls_total",
    "Total number of LLM kickoff calls",
    ["stage", "market"],
)

db_upserts_total = Counter(
    "db_upserts_total",
    "Total number of DB upserted/inserted records",
    ["source", "market"],
)

scrape_success_total = Counter(
    "scrape_success_total",
    "Total number of successful stage-1 scrapes",
    ["market"],
)

scraper_runs_total = Counter(
    "scraper_runs_total",
    "Scraper runs by source, market, and status",
    ["source", "market", "status"],
)

# Known market names — used to sanitise scraper counter labels, preventing
# accidental high-cardinality from freeform input (e.g. IGR --market flag).
_VALID_MARKETS = frozenset({"Yelahanka", "Devanahalli", "Hebbal", "all"})


def safe_scraper_market(market: str) -> str:
    """Sanitize market name for Prometheus label. Falls back to 'unknown' if not recognised."""
    if not market or not isinstance(market, str):
        return "unknown"
    cleaned = market.strip().title()
    if cleaned in _VALID_MARKETS:
        return cleaned
    return "unknown"

llm_router_fallbacks_total = Counter(
    "llm_router_fallbacks_total",
    "LLM router provider exclusions/fallbacks by tier and provider",
    ["tier", "provider"],
)

pipeline_stage_duration_seconds = Histogram(
    "pipeline_stage_duration_seconds",
    "Pipeline stage wall-clock duration in seconds",
    ["stage"],
    buckets=(10, 30, 60, 120, 300, 600, 1200, 1800, 3600),
)

db_query_duration_seconds = Histogram(
    "db_query_duration_seconds",
    "Database query duration in seconds",
    ["query_name"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
)

data_quality_checks_total = Counter(
    "data_quality_checks_total",
    "Data quality check results by market and status (pass/fail/skipped/error/db_error)",
    ["market", "status"],
)
