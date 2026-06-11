"""GATE-89 declaration — Data Quality panel, provenance, scraper reliability, data floor.

Five unit-safe assertions:
1. GET /api/data/provenance returns 200 with 'Yelahanka' key (mocked DB).
2. GET /api/scraper/reliability returns 200 with >=1 scraper key (mocked DB).
3. 'data_floor_check' job ID in config/scheduler.py.
4. dashboard/templates/data_quality.html exists.
5. compute_scraper_reliability callable from utils.scraper_reliability.
"""

import os
import pytest
pytestmark = pytest.mark.unit

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


def test_gate89_provenance_endpoint():
    """Assert 1: /api/data/provenance returns 200 with Yelahanka key."""
    from unittest.mock import MagicMock, patch
    mock_row = MagicMock()
    mock_row.__getitem__.side_effect = lambda idx: ["Yelahanka", "portal_scraped", 100][idx]
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [mock_row]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_engine):
        r = client.get("/api/data/provenance")
    assert r.status_code == 200
    body = r.json()
    assert "Yelahanka" in body
    assert "guidance" in body["Yelahanka"]


def test_gate89_reliability_endpoint():
    """Assert 2: /api/scraper/reliability returns 200 with >=1 scraper key."""
    from unittest.mock import MagicMock, patch
    mock_row = MagicMock()
    mock_row.__getitem__.side_effect = lambda idx: [10, 8, "2026-06-11 06:00:00"][idx]
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("utils.scraper_reliability.get_engine", return_value=mock_engine):
        r = client.get("/api/scraper/reliability")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1


def test_gate89_data_floor_job():
    """Assert 3: data_floor_check job ID in scheduler.py."""
    with open("config/scheduler.py", encoding="utf-8") as f:
        content = f.read()
    assert "data_floor_check" in content


def test_gate89_template_exists():
    """Assert 4: data_quality.html exists."""
    path = os.path.join(
        os.path.dirname(__file__), "..",
        "dashboard", "templates", "data_quality.html",
    )
    assert os.path.exists(path), "data_quality.html not found"


def test_gate89_compute_callable():
    """Assert 5: compute_scraper_reliability callable from utils.scraper_reliability."""
    from utils.scraper_reliability import compute_scraper_reliability
    assert callable(compute_scraper_reliability)
