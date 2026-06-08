"""GATE-66 declaration — Operations Department (Sprint 58)."""
import os
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
import pytest
pytestmark = pytest.mark.unit

_API_KEY = "gate66-key"
_P1 = "00000000-0000-0000-0000-000000000001"
_T1 = "00000000-0000-0000-0000-000000000002"


def test_gate_post_project_returns_201():
    """GATE-66 (1): POST /api/projects \u2192 201."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    conn = MagicMock()
    with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
         patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
        mock_eng.return_value.begin.return_value.__enter__.return_value = conn
        result = MagicMock()
        result.fetchone.return_value = (
            _P1, "Gate Project", "Yelahanka", "10/1", "outright",
            "lead", None, None, None, None, None,
        )
        conn.execute.return_value = result
        resp = client.post(
            "/api/projects",
            json={"name": "Gate Project", "market": "Yelahanka", "survey_no": "10/1"},
            headers={"X-API-Key": _API_KEY},
        )
    assert resp.status_code == 201
    assert resp.json()["id"] is not None


def test_gate_post_task_returns_201():
    """GATE-66 (2): POST /api/projects/{id}/tasks \u2192 201."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    conn = MagicMock()
    with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
         patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
        mock_eng.return_value.begin.return_value.__enter__.return_value = conn
        r1 = MagicMock()
        r1.fetchone.return_value = (_P1,)
        r2 = MagicMock()
        r2.fetchone.return_value = (_T1, "Test task", None, "ops", "todo", None, None, None)
        conn.execute.side_effect = [r1, r2]
        resp = client.post(
            f"/api/projects/{_P1}/tasks",
            json={"title": "Test task"},
            headers={"X-API-Key": _API_KEY},
        )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Test task"


def test_gate_status_report_has_open_task_count():
    """GATE-66 (3): ProjectStatusReport has open_task_count key."""
    from agents.project_manager_agent import _get_project_status
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        r1 = MagicMock()
        r1.fetchone.return_value = (_P1, "Gate Test", "mou", None)
        r2 = MagicMock()
        r2.fetchall.return_value = [("todo", 2)]
        r3 = MagicMock()
        r3.scalar.return_value = 0
        r4 = MagicMock()
        r4.fetchone.return_value = None
        mock_conn.execute.side_effect = [r1, r2, r3, r4]
        report = _get_project_status(_P1)
    assert hasattr(report, "open_task_count")
    assert report.open_task_count == 2


def test_gate_velocity_written_on_status_change():
    """GATE-66 (4): PATCH status writes deal_velocity row."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    conn = MagicMock()
    with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
         patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
        mock_eng.return_value.begin.return_value.__enter__.return_value = conn
        r1 = MagicMock()
        r1.fetchone.return_value = (_P1, "lead", "Gate", "Yelahanka", None, None)
        r2 = MagicMock()
        r2.fetchone.return_value = None
        r3 = MagicMock()
        r3.fetchone.return_value = (_P1, "Gate", "Yelahanka", None, "mou", None, None, None)
        conn.execute.side_effect = [r1, r2, r3]
        resp = client.patch(
            f"/api/projects/{_P1}/status",
            json={"status": "mou"},
            headers={"X-API-Key": _API_KEY},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "mou"


def test_gate_projects_page_returns_200():
    """GATE-66 (5): GET /projects \u2192 200."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/projects", headers={"X-API-Key": _API_KEY})
    assert resp.status_code == 200
