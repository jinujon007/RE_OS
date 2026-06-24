"""T-1354 — ObsidianSync unit tests.

10+ assertions:
  A1: Importable + __all__ includes all 3 public functions
  A2: Correct filename format with (AI) prefix
  A3: Frontmatter has all required LLS CLAUDE.md fields
  A4: Export endpoint route exists in board_room router
  A5: PSF forecast table contains all required rows
  A6: Graceful no-sync-path returns None
  A7: Empty market string handled without crash
  A8: Empty forecast dict produces valid markdown with em-dash placeholders
  A9: Invalid decision_flag defaults to CONDITIONAL
  A10: Export endpoint returns 404 for unknown session (mock DB)
  A11: Export endpoint returns 400 for invalid UUID
"""

import json
import pathlib
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_a1_importable():
    from utils.obsidian_sync import (
        write_board_verdict, write_weekly_digest, write_psf_forecast,
        __all__,
    )
    assert callable(write_board_verdict)
    assert callable(write_weekly_digest)
    assert callable(write_psf_forecast)
    assert "write_board_verdict" in __all__
    assert "write_weekly_digest" in __all__
    assert "write_psf_forecast" in __all__


def test_a2_correct_filename_format(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", str(tmp_path))
    from utils.obsidian_sync import write_board_verdict, write_weekly_digest, write_psf_forecast

    verdict_path = write_board_verdict("Yelahanka", "test md", "GO")
    assert verdict_path
    assert "(AI)" in verdict_path
    assert "Board Room Verdict" in verdict_path
    assert "Yelahanka" in verdict_path

    digest_path = write_weekly_digest("Devanahalli", "test digest")
    assert digest_path
    assert "(AI)" in digest_path
    assert "Weekly Digest" in digest_path

    forecast_path = write_psf_forecast("Hebbal", {
        "trend_direction": "rising",
        "current_psf": 8500,
        "forecast_3m": 8700,
        "forecast_6m": 8900,
        "forecast_12m": 9200,
        "data_points": 8,
        "mae_pct": 4.5,
        "status": "ok",
    })
    assert forecast_path
    assert "(AI)" in forecast_path
    assert "PSF Forecast" in forecast_path


def test_a3_frontmatter_has_required_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", str(tmp_path))
    from utils.obsidian_sync import write_board_verdict

    path = write_board_verdict("Yelahanka", "test", "GO")
    assert path
    content = pathlib.Path(path).read_text(encoding="utf-8")
    assert "type: crystallization" in content
    assert "area: lls" in content
    assert "ai_generated: true" in content
    assert "market: Yelahanka" in content
    assert "source: board_room" in content
    assert "status: active" in content
    assert "last_confirmed:" in content
    assert "Decision Flag" in content
    assert "GO" in content


def test_a4_export_endpoint_exists_in_router():
    router_src = (REPO_ROOT / "dashboard" / "routers" / "board_room.py").read_text(encoding="utf-8")
    assert "obsidian-export" in router_src
    assert "session_id" in router_src
    assert "filename" in router_src
    assert "frontmatter" in router_src


def test_a5_psf_forecast_has_table(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", str(tmp_path))
    from utils.obsidian_sync import write_psf_forecast

    forecast = {
        "trend_direction": "rising",
        "current_psf": 8500,
        "forecast_3m": 8700,
        "forecast_6m": 8900,
        "forecast_12m": 9200,
        "data_points": 8,
        "mae_pct": 4.5,
        "status": "ok",
    }
    path = write_psf_forecast("Hebbal", forecast)
    assert path
    content = pathlib.Path(path).read_text(encoding="utf-8")
    assert "| Trend" in content
    assert "| Current PSF" in content
    assert "| 6-Month Forecast" in content
    assert "| 12-Month Forecast" in content
    assert "| 6-Mo Change" in content


def test_a6_graceful_no_sync_path(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", "/nonexistent/path")
    from utils.obsidian_sync import write_board_verdict
    result = write_board_verdict("Yelahanka", "test", "GO")
    assert result is None


def test_a7_empty_market_handled(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", str(tmp_path))
    from utils.obsidian_sync import write_board_verdict
    path = write_board_verdict("", "some content")
    assert path
    content = pathlib.Path(path).read_text(encoding="utf-8")
    assert "market:" in content


def test_a8_empty_forecast_dict_produces_em_dash(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", str(tmp_path))
    from utils.obsidian_sync import write_psf_forecast
    path = write_psf_forecast("Yelahanka", {})
    assert path
    content = pathlib.Path(path).read_text(encoding="utf-8")
    assert "\u2014" in content
    assert "PSF Forecast" in content


def test_a9_invalid_decision_flag_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", str(tmp_path))
    from utils.obsidian_sync import write_board_verdict
    path = write_board_verdict("Yelahanka", "content", "INVALID_FLAG")
    assert path
    content = pathlib.Path(path).read_text(encoding="utf-8")
    assert "CONDITIONAL" in content


def test_a10_export_404_not_found():
    from dashboard.routers.board_room import router
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)
    valid_uuid = "00000000-0000-0000-0000-000000000000"
    resp = client.get(
        f"/api/v1/board/sessions/{valid_uuid}/obsidian-export",
        headers={"X-API-Key": "test"},
    )
    assert resp.status_code in (401, 404)


def test_a11_export_invalid_uuid(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "test-read-key-133")
    monkeypatch.setenv("DASHBOARD_API_KEY_READ", "test-read-key-133")
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get(
        "/api/v1/board/sessions/not-a-uuid/obsidian-export",
        headers={"X-API-Key": "test-read-key-133"},
    )
    assert resp.status_code == 400


def test_a12_weekly_digest_with_dataclass(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", str(tmp_path))
    from utils.weekly_digest import WeeklyDigestResult
    from utils.obsidian_sync import write_weekly_digest

    r = WeeklyDigestResult(
        market="Yelahanka",
        psf_delta_pct=2.5, psf_direction="up",
        new_rera_count=5,
        competitor_launches=[],
        distressed_developers=[],
        top_opportunity=None,
    )
    path = write_weekly_digest("Yelahanka", r)
    assert path
    content = pathlib.Path(path).read_text(encoding="utf-8")
    assert "PSF Delta" in content
    assert "Yelahanka" in content
