"""Unit tests for /api/projects CRUD + deal velocity (T-995)."""
import os
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
import pytest
pytestmark = pytest.mark.unit

_API_KEY = "test-key"
_P1 = "00000000-0000-0000-0000-000000000001"
_T1 = "00000000-0000-0000-0000-000000000002"


class TestCreateProject:
    def test_create_project(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        conn = MagicMock()
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
             patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
            mock_eng.return_value.begin.return_value.__enter__.return_value = conn
            result = MagicMock()
            result.fetchone.return_value = (
                _P1, "Test Project", "Yelahanka", "45/2", "compare",
                "lead", None, None, None, None, None,
            )
            conn.execute.return_value = result
            resp = client.post(
                "/api/projects",
                json={"name": "Test Project", "market": "Yelahanka",
                       "survey_no": "45/2", "deal_type": "compare"},
                headers={"X-API-Key": _API_KEY},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Project"
        assert data["status"] == "lead"

    def test_create_project_invalid_status(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
            resp = client.post(
                "/api/projects",
                json={"name": "Test", "status": "invalid_status"},
                headers={"X-API-Key": _API_KEY},
            )
        assert resp.status_code == 400


class TestListProjects:
    def test_list_with_status_filter(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        conn = MagicMock()
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
             patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
            mock_eng.return_value.connect.return_value.__enter__.return_value = conn
            result = MagicMock()
            result.scalar.return_value = 1
            result.fetchall.return_value = [
                (_P1, "Test", "Yelahanka", "45/2", "compare", "lead", None, None, 10, 2),
            ]
            conn.execute.side_effect = [result, result]
            resp = client.get(
                "/api/projects?status=lead",
                headers={"X-API-Key": _API_KEY},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "projects" in data
        assert len(data["projects"]) == 1
        assert data["projects"][0]["status"] == "lead"


class TestGetProject:
    def test_get_project_with_tasks(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        conn = MagicMock()
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
             patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
            mock_eng.return_value.connect.return_value.__enter__.return_value = conn
            conn.execute.side_effect = [
                MagicMock(fetchone=lambda: (
                    _P1, "Test", "Yelahanka", "45/2", "compare",
                    "lead", None, None, None, None, None, None, 10,
                )),
                MagicMock(fetchall=lambda: [
                    (_T1, "Task A", None, "ops", "todo", None, None, None, None),
                ]),
                MagicMock(fetchall=lambda: []),
            ]
            resp = client.get(
                f"/api/projects/{_P1}",
                headers={"X-API-Key": _API_KEY},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "project" in data
        assert "tasks" in data
        assert len(data["tasks"]) == 1

    def test_get_project_invalid_id(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        with patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
            resp = client.get(
                "/api/projects/not-a-uuid",
                headers={"X-API-Key": _API_KEY},
            )
        assert resp.status_code == 400


class TestCreateTask:
    def test_create_task(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        conn = MagicMock()
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
             patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
            mock_eng.return_value.begin.return_value.__enter__.return_value = conn
            r1 = MagicMock()
            r1.fetchone.return_value = (_P1,)
            r2 = MagicMock()
            r2.fetchone.return_value = (
                _T1, "New Task", None, "ops", "todo", None, None, None,
            )
            conn.execute.side_effect = [r1, r2]
            resp = client.post(
                f"/api/projects/{_P1}/tasks",
                json={"title": "New Task", "dept": "ops"},
                headers={"X-API-Key": _API_KEY},
            )
        assert resp.status_code == 201
        assert resp.json()["title"] == "New Task"


class TestTaskCompletion:
    def test_task_completion_sets_timestamp(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        conn = MagicMock()
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
             patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
            mock_eng.return_value.begin.return_value.__enter__.return_value = conn
            result = MagicMock()
            result.fetchone.return_value = (_T1, "Task A", "done", None, None)
            conn.execute.return_value = result
            resp = client.patch(
                f"/api/projects/{_P1}/tasks/{_T1}",
                json={"status": "done"},
                headers={"X-API-Key": _API_KEY},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"


class TestVelocity:
    def test_velocity_written_on_status_change(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        conn = MagicMock()
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
             patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
            mock_eng.return_value.begin.return_value.__enter__.return_value = conn
            r1 = MagicMock()
            r1.fetchone.return_value = (_P1, "lead", "Test", "Yelahanka", None, None)
            r2 = MagicMock()
            r2.fetchone.return_value = None
            r3 = MagicMock()
            r3.fetchone.return_value = (
                _P1, "Test", "Yelahanka", None, "mou", None, None, None,
            )
            conn.execute.side_effect = [r1, r2, r3]
            resp = client.patch(
                f"/api/projects/{_P1}/status",
                json={"status": "mou"},
                headers={"X-API-Key": _API_KEY},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "mou"

    def test_velocity_endpoint(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        conn = MagicMock()
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng, \
             patch.dict(os.environ, {"DASHBOARD_API_KEY": _API_KEY}):
            mock_eng.return_value.connect.return_value.__enter__.return_value = conn
            conn.execute.side_effect = [
                MagicMock(fetchone=lambda: (_P1, "lead", None)),
                MagicMock(fetchall=lambda: [("start", "lead", 0, None)]),
            ]
            resp = client.get(
                f"/api/projects/{_P1}/velocity",
                headers={"X-API-Key": _API_KEY},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "stages" in data
        assert "current_stage" in data
