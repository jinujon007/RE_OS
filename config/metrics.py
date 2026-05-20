"""Shared Prometheus metrics for RE_OS runtime hooks."""

from prometheus_client import Counter


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
