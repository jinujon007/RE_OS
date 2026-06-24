"""GATE-128 — RERA Scraper Resilience: Circuit Breaker + 7-Day Cache Fallback.

5 assertions (all code-verifiable without Docker):
A1: ScraperCircuitBreaker + CircuitOpenError importable
A2: rera_karnataka.py uses circuit breaker (source check)
A3: scraper_health_check job registered in scheduler (source check)
A4: Circuit breaker retries before falling back (delay called twice)
A5: CircuitOpenError raised when no cache available (no silent swallow)
"""

import pathlib
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_gate128_a1_imports():
    """A1: ScraperCircuitBreaker + CircuitOpenError importable."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker, CircuitOpenError, ScraperResult

    assert callable(ScraperCircuitBreaker)
    assert issubclass(CircuitOpenError, Exception)
    inst = ScraperResult(data="x", from_cache=False, cache_age_days=None, attempts_made=0)
    assert hasattr(inst, "data")
    assert hasattr(inst, "from_cache")
    assert hasattr(inst, "attempts_made")
    assert hasattr(CircuitOpenError("test", market="m", attempts_made=3, last_error="e"), "market")
    assert hasattr(CircuitOpenError("test", market="m", attempts_made=3, last_error="e"), "attempts_made")
    assert hasattr(CircuitOpenError("test", market="m", attempts_made=3, last_error="e"), "last_error")


def test_gate128_a2_wired_in_rera():
    """A2: rera_karnataka.py imports and uses ScraperCircuitBreaker."""
    src = (REPO_ROOT / "scrapers" / "rera_karnataka.py").read_text(encoding="utf-8")
    assert "ScraperCircuitBreaker" in src, (
        "rera_karnataka.py must import ScraperCircuitBreaker"
    )
    assert "CircuitOpenError" in src, (
        "rera_karnataka.py must catch CircuitOpenError"
    )
    assert "cb.run" in src, (
        "rera_karnataka.py must call cb.run()"
    )
    assert "from_cache" in src, (
        "rera_karnataka.py must check result.from_cache"
    )


def test_gate128_a3_scraper_health_job_registered():
    """A3: scraper_health_check job registered in scheduler."""
    src = (REPO_ROOT / "config" / "scheduler" / "maintenance_jobs.py").read_text(encoding="utf-8")
    assert "def run_scraper_health_check" in src, (
        "maintenance_jobs.py must define run_scraper_health_check"
    )
    assert "scraper_health_check" in src, (
        "maintenance_jobs.py must register scraper_health_check job id"
    )
    assert "RERA_DATA_STALE" in src, (
        "run_scraper_health_check must fire RERA_DATA_STALE alert"
    )

    init_src = (REPO_ROOT / "config" / "scheduler" / "__init__.py").read_text(encoding="utf-8")
    assert "run_scraper_health_check" in init_src, (
        "scheduler __init__.py must export run_scraper_health_check"
    )


def test_gate128_a4_retry_before_cache():
    """A4: Circuit breaker retries with delay before falling back to cache."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker, CircuitOpenError

    call_count: list[int] = [0]

    def always_fails():
        call_count[0] += 1
        raise RuntimeError("persistent failure")

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)

    with patch.object(cb._checkpointer, "base_dir", "/nonexistent"):
        with patch("utils.scraper_circuit_breaker.time.sleep") as mock_sleep:
            with pytest.raises(CircuitOpenError) as exc_info:
                cb.run(always_fails)

    assert call_count[0] == 3, (
        f"Expected 3 attempts, got {call_count[0]}"
    )
    assert mock_sleep.call_count == 2, (
        f"Expected 2 backoff delays, got {mock_sleep.call_count}"
    )
    assert exc_info.value.market == "TestMarket"
    assert exc_info.value.attempts_made == 3


def test_gate128_a5_circuit_open_no_cache():
    """A5: CircuitOpenError raised when no cache available (no silent swallow)."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker, CircuitOpenError

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)

    def _failing():
        raise RuntimeError("no data")

    with patch.object(cb._checkpointer, "base_dir", "/nonexistent"):
        with patch("utils.scraper_circuit_breaker.time.sleep"):
            with pytest.raises(CircuitOpenError) as exc_info:
                cb.run(_failing)

    assert "3 attempts failed" in str(exc_info.value), (
        f"Error message should mention attempts: {exc_info.value}"
    )
    assert "no valid cache" in str(exc_info.value), (
        f"Error message should mention cache: {exc_info.value}"
    )
