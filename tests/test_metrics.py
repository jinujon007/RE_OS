"""Smoke tests for Prometheus metrics registration and label integrity."""

import pytest

pytestmark = pytest.mark.unit

from prometheus_client import REGISTRY

# Import the metrics module to ensure all metrics are registered
import config.metrics  # noqa: F401


def _metric_exists(metric_name: str) -> bool:
    """Check if a metric name (without _total suffix) is registered."""
    for metric in REGISTRY.collect():
        if metric.name == metric_name:
            return True
    return False


class TestMetricsExist:
    def test_pipeline_runs_registered(self):
        assert _metric_exists("pipeline_runs")

    def test_llm_calls_registered(self):
        assert _metric_exists("llm_calls")

    def test_db_upserts_registered(self):
        assert _metric_exists("db_upserts")

    def test_scrape_success_registered(self):
        assert _metric_exists("scrape_success")

    def test_scraper_runs_registered(self):
        assert _metric_exists("scraper_runs")

    def test_llm_router_fallbacks_registered(self):
        assert _metric_exists("llm_router_fallbacks")

    def test_pipeline_stage_duration_seconds_registered(self):
        assert _metric_exists("pipeline_stage_duration_seconds")

    def test_db_query_duration_seconds_registered(self):
        assert _metric_exists("db_query_duration_seconds")


class TestMetricsLabelIntegrity:
    def test_pipeline_runs_labels(self):
        from config.metrics import pipeline_runs_total

        # Should accept market label
        pipeline_runs_total.labels(market="test").inc()
        assert True  # no KeyError from invalid label

    def test_llm_calls_labels(self):
        from config.metrics import llm_calls_total

        llm_calls_total.labels(stage="test", market="test").inc()
        assert True

    def test_scraper_runs_labels(self):
        from config.metrics import scraper_runs_total

        scraper_runs_total.labels(source="test", market="test", status="success").inc()
        assert True

    def test_llm_router_fallbacks_labels(self):
        from config.metrics import llm_router_fallbacks_total

        llm_router_fallbacks_total.labels(tier="heavy", provider="groq").inc()
        assert True

    def test_pipeline_stage_duration_labels(self):
        from config.metrics import pipeline_stage_duration_seconds

        pipeline_stage_duration_seconds.labels(stage="data_crew").observe(1.0)
        assert True

    def test_db_query_duration_labels(self):
        from config.metrics import db_query_duration_seconds

        db_query_duration_seconds.labels(query_name="v_market_brief").observe(0.5)
        assert True


class TestSafeScraperMarket:
    def test_known_market_unchanged(self):
        from config.metrics import safe_scraper_market

        assert safe_scraper_market("Yelahanka") == "Yelahanka"

    def test_known_market_case_insensitive(self):
        from config.metrics import safe_scraper_market

        assert safe_scraper_market("yelahanka") == "Yelahanka"

    def test_unknown_market_falls_back(self):
        from config.metrics import safe_scraper_market

        assert safe_scraper_market("NonexistentCity") == "unknown"

    def test_none_market_falls_back(self):
        from config.metrics import safe_scraper_market

        assert safe_scraper_market(None) == "unknown"

    def test_empty_market_falls_back(self):
        from config.metrics import safe_scraper_market

        assert safe_scraper_market("") == "unknown"
