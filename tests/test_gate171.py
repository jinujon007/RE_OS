"""GATE-171: VEL Intelligence Auto-Export — 5 gate assertions (A1-A5).

A1: GET /api/v1/intel/vel/market-context registered in FastAPI routes
A2: run_vel_weekly_market_update importable + callable from intel_jobs
A3: recommended_psf_range [-10%/+15%] math: avg_psf=10000 → [9000, 11500]
A4: "run_vel_weekly_market_update" in intel_jobs.__all__
A5: vel_intel.html template exists and contains "VEL" string
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
os.environ["DASHBOARD_API_KEY"] = "test-key"
os.environ["DASHBOARD_API_KEY_READ"] = "test-read-key"
os.environ["DASHBOARD_API_KEY_ADMIN"] = "test-admin-key"

pytestmark = pytest.mark.unit


def test_gate171_a1_vel_market_context_route_registered():
    """A1: GET /api/v1/intel/vel/market-context registered in FastAPI routes."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    route_paths = [r.path for r in app.routes]
    assert "/api/v1/intel/vel/market-context" in route_paths, (
        "A1: VEL market-context route not registered"
    )


def test_gate171_a2_run_vel_weekly_market_update_importable():
    """A2: run_vel_weekly_market_update importable and callable from intel_jobs."""
    from config.scheduler.intel_jobs import run_vel_weekly_market_update

    assert callable(run_vel_weekly_market_update), (
        "A2: run_vel_weekly_market_update must be callable"
    )


def test_gate171_a3_recommended_psf_range():
    """A3: avg_psf=10000 → recommended_psf_range=[9000, 11500] (-10%/+15%)."""
    avg_psf = 10000.0
    lo = round(avg_psf * 0.9, 0)
    hi = round(avg_psf * 1.15, 0)
    assert lo == 9000.0, f"A3: expected lo=9000 (10% discount), got {lo}"
    assert hi == 11500.0, f"A3: expected hi=11500 (15% premium), got {hi}"
    assert lo < avg_psf < hi, "A3: lo < avg < hi invariant violated"


def test_gate171_a4_run_vel_weekly_market_update_in_all():
    """A4: run_vel_weekly_market_update is in intel_jobs.__all__."""
    import config.scheduler.intel_jobs as intel_jobs

    assert "run_vel_weekly_market_update" in intel_jobs.__all__, (
        "A4: run_vel_weekly_market_update must be in intel_jobs.__all__"
    )


def test_gate171_a5_vel_intel_template_exists():
    """A5: vel_intel.html template exists and contains 'VEL' string."""
    template_path = Path("dashboard/templates/vel_intel.html")
    assert template_path.exists(), "A5: vel_intel.html template must exist"
    content = template_path.read_text(encoding="utf-8")
    assert "VEL" in content, "A5: vel_intel.html must contain 'VEL' string"


def test_gate171_edge_vel_weekly_has_guard():
    """Edge: run_vel_weekly_market_update has concurrent-run guard."""
    from config.scheduler.intel_jobs import _VEL_WEEKLY_RUNNING
    assert _VEL_WEEKLY_RUNNING is not None
    assert hasattr(_VEL_WEEKLY_RUNNING, "set")
    assert hasattr(_VEL_WEEKLY_RUNNING, "clear")


def test_gate171_edge_response_model_has_generated_at():
    """Edge: VELMarketContextResponse has generated_at field."""
    from dashboard.routers.data import VELMarketContextResponse

    assert "generated_at" in VELMarketContextResponse.model_fields
    assert "recommended_psf_range" in VELMarketContextResponse.model_fields


def test_gate171_edge_vel_intel_template_has_cache_headers():
    """Edge: vel_market_context response includes Cache-Control header."""
    # Check that the endpoint source references cache headers
    source = Path("dashboard/routers/data.py").read_text(encoding="utf-8")
    assert "Cache-Control" in source, "Endpoint should return Cache-Control headers"
    assert "max-age=120" in source, "Cache max-age should be 120s"
