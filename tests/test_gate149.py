"""GATE-149: V2.0 Operational Declaration — 5 gate assertions (A1-A5).

A1: GET /api/v1/ops/kill-criteria returns 200 with deed_throughput.status + decision_journal.status
A2: GET /api/v1/ops/handover-doc returns 200 text/markdown with "Kill Criteria" + "Jinu Next Actions"
A3: GET /api/v1/ops/v2-readiness includes kill_criteria_deed_status + kill_criteria_journal_status
A4: dashboard/templates/v2_readiness.html contains "kill-criteria" + "declare"
A5: All 4 new routes present in FastAPI app
"""

import os
import pathlib
from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.unit


# ── A1: Kill criteria endpoint ────────────────────────────────────────────


def test_gate149_a1_kill_criteria_returns_status_and_target():
    """A1: GET /api/v1/ops/kill-criteria returns deed_throughput.status + decision_journal.status."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("utils.deed_progress.compute_throughput_projection") as mock_proj,
        patch("utils.decision_journal.list_entries") as mock_list,
    ):
        mock_proj.return_value = {
            "avg_4wk": 12.5,
            "weeks_remaining": 7,
            "required_rate": 50,
            "projection_verdict": "at_risk",
            "deadline": "2026-08-15",
        }
        mock_list.return_value = [{"id": 1, "decision_flag": "GO"}]

        resp = client.get("/api/v1/ops/kill-criteria")

    assert resp.status_code == 200
    data = resp.json()
    assert "deed_throughput" in data
    assert "decision_journal" in data
    assert data["deed_throughput"]["status"] == "at_risk"
    assert data["decision_journal"]["status"] == "met"
    assert data["deed_throughput"]["target"] == 50
    assert data["decision_journal"]["deadline"] == "2026-12-31"
    assert "generated_at" in data


def test_gate149_a1_kill_criteria_empty_journal_returns_unmet():
    """A1: kill-criteria returns decision_journal.status=unmet when no entries exist."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("utils.deed_progress.compute_throughput_projection") as mock_proj,
        patch("utils.decision_journal.list_entries", return_value=[]),
    ):
        mock_proj.return_value = {"avg_4wk": 52.0, "projection_verdict": "on_track", "weeks_remaining": 7}
        resp = client.get("/api/v1/ops/kill-criteria")

    assert resp.status_code == 200
    data = resp.json()
    assert data["deed_throughput"]["status"] == "on_track"
    assert data["decision_journal"]["status"] == "unmet"
    assert data["decision_journal"]["entry_count"] == 0


def test_gate149_a1_kill_criteria_fallback_on_error():
    """A1: kill-criteria returns unknown status when underlying calls fail."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("utils.deed_progress.compute_throughput_projection", side_effect=RuntimeError("db down")),
        patch("utils.decision_journal.list_entries", side_effect=RuntimeError("no table")),
    ):
        resp = client.get("/api/v1/ops/kill-criteria")

    assert resp.status_code == 200
    data = resp.json()
    assert data["deed_throughput"]["status"] == "unknown"
    assert data["decision_journal"]["status"] == "unknown"


# ── A2: Handover doc endpoint ─────────────────────────────────────────────


def test_gate149_a2_handover_doc_returns_markdown():
    """A2: GET /api/v1/ops/handover-doc returns 200 text/markdown with expected sections."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    mock_conn = MagicMock()

    def mock_execute_side_effect(query, **kwargs):
        txt = str(query) if hasattr(query, '__str__') else str(query)
        result = MagicMock()
        if "agent_runs" in txt and "ORDER BY created_at DESC LIMIT 1" in txt:
            result.fetchone.return_value = ("scheduler", "success", "2026-06-27T00:00:00+00:00")
        elif "COUNT(*) FROM rera_projects" in txt:
            result.scalar.return_value = 45
        elif "AVG(psf)" in txt:
            result.scalar.return_value = 6200.0
        elif "ORDER BY created_at DESC LIMIT 1" in txt and "agent_runs" not in txt:
            result.fetchone.return_value = ("2026-06-27T00:00:00+00:00",)
        elif "board_sessions" in txt:
            result.fetchone.return_value = ("All markets stable. No escalations.",)
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
            result.scalar.return_value = 0
        return result

    mock_conn.execute.side_effect = mock_execute_side_effect

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_engine,
        patch("utils.deed_progress.compute_throughput_projection") as mock_proj,
        patch("utils.decision_journal.list_entries") as mock_list,
        patch("dashboard.state._get_sa_engine") as mock_state_engine,
    ):
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_state_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_proj.return_value = {"avg_4wk": 12.5, "projection_verdict": "at_risk"}
        mock_list.return_value = [{"id": 1}]

        resp = client.get("/api/v1/ops/handover-doc")

    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/markdown")
    body = resp.text
    assert "Kill Criteria" in body
    assert "Jinu Next Actions" in body
    assert "Yelahanka" in body
    assert "Devanahalli" in body
    assert "Hebbal" in body


def test_gate149_a2_handover_doc_graceful_degradation():
    """A2: handover-doc returns 200 with 'Data unavailable' placeholders when DB fails."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = RuntimeError("connection refused")

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_engine,
        patch("dashboard.state._get_sa_engine") as mock_state_engine,
    ):
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_state_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        resp = client.get("/api/v1/ops/handover-doc")

    assert resp.status_code == 200
    body = resp.text
    assert "Data unavailable" in body
    assert "Jinu Next Actions" in body


# ── A3: v2-readiness kill criteria fields ─────────────────────────────────


def test_gate149_a3_v2_readiness_has_kill_criteria_keys():
    """A3: GET /api/v1/ops/v2-readiness includes kill_criteria_deed_status + kill_criteria_journal_status."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    from dashboard.routers.ops import V2ReadinessResponse
    client = TestClient(app)

    mock_resp = V2ReadinessResponse(
        v2_ready=False, scheduler_days_running=14, scheduler_success_rate=0.95,
        discord_digest_count=3, live_rera_growth=True, board_room_avg_response_s=42.5,
        kill_criteria_deed_status="at_risk", kill_criteria_journal_status="met", weeks_remaining=7,
    )

    with (
        patch("dashboard.routers.ops._compute_v2_readiness", return_value=mock_resp),
        patch("dashboard.routers.ops._get_sa_engine") as mock_engine,
        patch("dashboard.state._get_sa_engine") as mock_state_engine,
    ):
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_state_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        resp = client.get("/api/v1/ops/v2-readiness")

    assert resp.status_code == 200
    data = resp.json()
    assert "kill_criteria_deed_status" in data
    assert "kill_criteria_journal_status" in data
    assert "weeks_remaining" in data
    assert data["kill_criteria_deed_status"] == "at_risk"
    assert data["kill_criteria_journal_status"] == "met"





# ── A4: Template contains required strings ────────────────────────────────


def test_gate149_a4_template_has_kill_criteria_and_declare():
    """A4: v2_readiness.html contains 'kill-criteria' and 'declare' (case-insensitive)."""
    template_path = pathlib.Path("dashboard/templates/v2_readiness.html")
    assert template_path.is_file(), "v2_readiness.html not found"
    content = template_path.read_text(encoding="utf-8").lower()
    assert "kill-criteria" in content, "Template missing 'kill-criteria'"
    assert "declare" in content, "Template missing 'declare'"


# ── A5: All 4 new routes present ──────────────────────────────────────────


def test_gate149_a5_all_new_routes_registered():
    """A5: All 4 new GATE-149 routes are registered in the FastAPI app."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    routes = [r.path for r in app.routes]
    assert "/api/v1/ops/kill-criteria" in routes
    assert "/api/v1/ops/handover-doc" in routes
    assert "/api/v1/ops/v2-readiness" in routes
    assert "/api/v1/ops/v2-declare" in routes
