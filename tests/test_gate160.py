"""GATE-160: Multi-Market Investor Digest — 5 gate assertions (A1-A5).

A1: run_weekly_investor_digest importable from config.scheduler.forecast_jobs + in __all__
A2: run_weekly_investor_digest() writes Obsidian + sends Telegram
A3: GET /api/v1/intel/investor/weekly-digest returns 200 + digest_markdown + markets_covered + generated_at
A4: STRR_STRONG_KM == 1.0 and STRR_MODERATE_KM == 3.0 from config.settings
A5: GET /api/v1/intel/investor/weekly-digest with no recent run returns source == "live"
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

os.environ["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
os.environ["DASHBOARD_API_KEY"] = "test-key"
os.environ["DASHBOARD_API_KEY_READ"] = "test-read-key"
os.environ["DASHBOARD_API_KEY_ADMIN"] = "test-admin-key"
os.environ["OBSIDIAN_SYNC_PATH"] = "/tmp/test_obsidian"

pytestmark = pytest.mark.unit


# ── A1: Importable + in __all__ ——————————————————————————————


def test_gate160_a1_importable_and_in_all():
    """A1: run_weekly_investor_digest importable + in __all__."""
    from config.scheduler.forecast_jobs import run_weekly_investor_digest, __all__

    assert callable(run_weekly_investor_digest)
    assert "run_weekly_investor_digest" in __all__


def test_gate160_a1_overlap_guard():
    """A1 edge: concurrent invocation is skipped."""
    from config.scheduler.forecast_jobs import run_weekly_investor_digest

    with (
        patch("config.scheduler.forecast_jobs._INVESTOR_DIGEST_RUNNING", True),
        patch("config.scheduler.forecast_jobs.TARGET_MARKETS", ["Yelahanka"]),
    ):
        result = run_weekly_investor_digest()

    assert result is None


# ── A2: Obsidian + Telegram ———————————————————————————————


def _mock_brief(overrides=None):
    from utils.investor_brief_generator import InvestorBrief

    b = InvestorBrief(
        market="Yelahanka",
        project_name="test",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        market_overview={"avg_psf": 5500, "psf_min": 4000, "psf_max": 8000, "listing_count": 100, "rera_projects": 50, "active_projects": 30, "psf_trend": {"direction": "up", "current_psf": 5500, "forecast_6m": 6000}},
        competitive_landscape={"grade_a_count": 5, "developers": []},
        financial_summary={"status": "insufficient_inputs"},
        supply_risk={"pipeline_units": 100, "active_units": 50, "weeks_of_inventory": 52},
        assembly_alerts=[],
        board_verdict={"status": "found", "decision_flag": "GO", "context_summary": "Test", "created_at": "2026-06-29", "assessments": {"bd": "positive", "finance": "ok"}},
    )
    return b


def test_gate160_a2_digest_generates_obsidian_and_telegram():
    """A2: run_weekly_investor_digest calls Obsidian + Telegram."""
    from config.scheduler.forecast_jobs import run_weekly_investor_digest

    mock_brief = _mock_brief()

    with (
        patch("config.scheduler.forecast_jobs.TARGET_MARKETS", ["Yelahanka"]),
        patch("utils.investor_brief_generator.InvestorBriefGenerator.generate", return_value=mock_brief),
        patch("utils.strr_overlay.STRROverlay.stations_near", return_value=[]),
        patch("utils.strr_overlay.STRROverlay.transit_signal", return_value="WEAK"),
        patch("utils.assembly_detector.AssemblyDetector.detect_clusters", return_value=[]),
        patch("utils.corridor_scorer.CorridorScorer.backtest_psf_history", return_value=[]),
        patch("utils.deed_progress.compute_throughput_projection", return_value={"avg_4wk": 30, "projection_verdict": "at_risk", "weeks_remaining": 7}),
        patch("utils.obsidian_sync.write_note") as mock_obsidian,
        patch("utils.telegram_notifier.send_message") as mock_tg,
        patch("utils.db.get_engine") as mock_eng,
    ):
        mock_eng.return_value.begin.return_value.__enter__.return_value = MagicMock()
        run_weekly_investor_digest()

    mock_obsidian.assert_called_once()
    path_arg = mock_obsidian.call_args[0][0]
    assert "Weekly Investor Digest" in path_arg
    mock_tg.assert_called_once()
    msg_arg = mock_tg.call_args[0][0]
    assert "Weekly Investor Digest" in msg_arg or "Yelahanka" in msg_arg


def test_gate160_a2_obsidian_failure_does_not_block_telegram():
    """A2 edge: Obsidian failure still sends Telegram."""
    from config.scheduler.forecast_jobs import run_weekly_investor_digest

    mock_brief = _mock_brief()

    with (
        patch("config.scheduler.forecast_jobs.TARGET_MARKETS", ["Yelahanka"]),
        patch("utils.investor_brief_generator.InvestorBriefGenerator.generate", return_value=mock_brief),
        patch("utils.strr_overlay.STRROverlay.stations_near", return_value=[]),
        patch("utils.strr_overlay.STRROverlay.transit_signal", return_value="WEAK"),
        patch("utils.assembly_detector.AssemblyDetector.detect_clusters", return_value=[]),
        patch("utils.corridor_scorer.CorridorScorer.backtest_psf_history", return_value=[]),
        patch("utils.deed_progress.compute_throughput_projection", return_value={"avg_4wk": 30, "projection_verdict": "at_risk", "weeks_remaining": 7}),
        patch("utils.obsidian_sync.write_note", return_value=""),
        patch("utils.telegram_notifier.send_message") as mock_tg,
        patch("utils.db.get_engine") as mock_eng,
    ):
        mock_eng.return_value.begin.return_value.__enter__.return_value = MagicMock()
        run_weekly_investor_digest()

    mock_tg.assert_called_once()


# ── A3: Weekly digest endpoint —————————————————————————————


def test_gate160_a3_weekly_digest_endpoint():
    """A3: GET /api/v1/intel/investor/weekly-digest returns 200 + keys."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = ("Test digest markdown content", datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc))
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_eng_fn = MagicMock(return_value=mock_engine)

    with patch("dashboard.routers.data._get_sa_engine", mock_eng_fn):
        resp = client.get(
            "/api/v1/intel/investor/weekly-digest",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "digest_markdown" in data
    assert data["digest_markdown"] == "Test digest markdown content"
    assert "markets_covered" in data
    assert "generated_at" in data
    assert data["markets_covered"] == ["Yelahanka", "Devanahalli", "Hebbal"]


def test_gate160_a3_weekly_digest_route_registered():
    """Digest route registered in data router."""
    from dashboard.routers.data import router

    route_paths = [r.path for r in router.routes]
    assert "/intel/investor/weekly-digest" in route_paths


# ── A4: STRR config constants —————————————————————————————


def test_gate160_a4_strr_constants():
    """A4: STRR_STRONG_KM == 1.0 and STRR_MODERATE_KM == 3.0."""
    from config.settings import STRR_STRONG_KM, STRR_MODERATE_KM

    assert STRR_STRONG_KM == 1.0
    assert STRR_MODERATE_KM == 3.0


def test_gate160_a4_strr_overlay_uses_settings():
    """A4 edge: transit_signal reads from settings."""
    from utils.strr_overlay import STRROverlay

    stations_strong = [{"name": "S1", "line": "Red", "lat": 13.1, "lon": 77.6, "status": "operational", "distance_km": 0.5}]
    stations_moderate = [{"name": "S1", "line": "Red", "lat": 13.1, "lon": 77.6, "status": "planned", "distance_km": 2.0}]
    stations_weak = [{"name": "S1", "line": "Red", "lat": 13.1, "lon": 77.6, "status": "planned", "distance_km": 5.0}]

    assert STRROverlay.transit_signal(stations_strong) == "STRONG"
    assert STRROverlay.transit_signal(stations_moderate) == "MODERATE"
    assert STRROverlay.transit_signal(stations_weak) == "WEAK"


# ── A5: Live fallback ———————————————————————————————


def test_gate160_a5_weekly_digest_live_fallback():
    """A5: no recent agent_runs row returns source=live."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    with (
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
        patch("dashboard.routers.data._WEEKLY_DIGEST_CACHE", {}),
        patch("config.scheduler.forecast_jobs.run_weekly_investor_digest") as mock_digest,
    ):
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_digest.return_value = None

        resp = client.get(
            "/api/v1/intel/investor/weekly-digest",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "source" in data
    assert data["source"] == "live"


# ── Module-level correctness ———————————————————————


def test_gate160_investor_digest_running_flag():
    """_INVESTOR_DIGEST_RUNNING flag exists."""
    from config.scheduler.forecast_jobs import _INVESTOR_DIGEST_RUNNING

    assert isinstance(_INVESTOR_DIGEST_RUNNING, bool)
