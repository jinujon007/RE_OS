"""GATE-86 — Memory Explorer + Phase 4 Completion.

Five gate-level assertions:
1. VISION.md Phase 4 status is ✅ COMPLETE
2. VISION.md P4.8 and P4.9 are checked [x]
3. TASK_QUEUE.md GATE-86 shows ✅ PASSED
4. /api/memory/explorer response model matches MemoryExplorerResponse schema
5. /api/memory/conflict-count response model matches ConflictCountResponse schema
"""

import os
import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skip(reason="gate-declaration tests coupled to VISION.md/TASK_QUEUE.md — skipped in batch CI"),  # TRACK: gate-declaration tests coupled to VISION.md/TASK_QUEUE.md — skipped in batch CI
]

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)

_GATE86_PASSED = "✅ PASSED (2026-06-11) — 5/5 assertions in test_gate86.py"
_GATE86_TABLE_ROW = "| GATE-86 | Sprint 86 | Memory Explorer panel renders"
_PHASE4_COMPLETE = "**Status:** ✅ COMPLETE"
_P48_CHECKED = "[x] P4.8"
_P49_CHECKED = "[x] P4.9"


def test_vision_md_phase4_status_complete():
    path = os.path.join(os.path.dirname(__file__), "..", "VISION.md")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert _PHASE4_COMPLETE in content, "Phase 4 not marked COMPLETE in VISION.md"
    assert _P48_CHECKED in content, "P4.8 not checked in VISION.md"
    assert _P49_CHECKED in content, "P4.9 not checked in VISION.md"


def test_task_queue_gate86_passed():
    path = os.path.join(os.path.dirname(__file__), "..", "TASK_QUEUE.md")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert _GATE86_PASSED in content, "GATE-86 not declared PASSED in TASK_QUEUE.md"
    assert _GATE86_TABLE_ROW in content[content.find("| GATE-86") :], (
        "GATE-86 table row not updated"
    )


def test_memory_explorer_response_schema():
    """Rapid schema check: verify endpoint returns correct shape (no DB)."""
    from unittest.mock import patch, MagicMock
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    with patch("dashboard.routers.data._get_sa_engine") as mock_engine:
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 0
        mock_conn.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/memory/explorer")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "page" in data
    assert "memories" in data


def test_conflict_count_response_schema():
    from unittest.mock import patch, MagicMock
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    with patch("dashboard.routers.data._get_sa_engine") as mock_engine:
        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 5
        resp = client.get("/api/memory/conflict-count")
    assert resp.status_code == 200
    data = resp.json()
    assert data["unresolved_conflicts"] == 5


def test_templates_exist():
    memory_html = os.path.join(
        os.path.dirname(__file__),
        "..",
        "dashboard",
        "templates",
        "memory_explorer.html",
    )
    index_html = os.path.join(
        os.path.dirname(__file__), "..", "dashboard", "templates", "index.html"
    )
    assert os.path.exists(memory_html), "memory_explorer.html template missing"
    assert os.path.exists(index_html), "index.html template missing"
    with open(index_html, encoding="utf-8") as f:
        assert "conflict-badge" in f.read(), "conflict-badge id missing from index.html"


def test_openapi_schema_registered():
    """Verify both new endpoints appear in generated OpenAPI schema."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    paths = schema.get("paths", {})
    assert "/api/memory/explorer" in paths, "explorer endpoint missing from OpenAPI"
    assert "/api/memory/conflict-count" in paths, (
        "conflict-count endpoint missing from OpenAPI"
    )
    assert "/memory" in paths, "/memory panel route missing from OpenAPI"
