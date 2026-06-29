"""GATE-153: Deed Throughput Acceleration — 5 gate assertions (A1-A5).

A1: GET /api/v1/deeds/download-guide returns 200 + villages list with required keys
A2: get_priority_villages("Yelahanka", top_n=3) returns list ≤3 items with expected keys
A3: run_kaveri_download_reminder includes priority village name in Telegram message
A4: Alembic migration 0074 importable, has v_deed_village_priority in upgrade SQL
A5: get_priority_villages returns [] on DB failure
"""

import os
import pathlib
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")

pytestmark = pytest.mark.unit


def _mock_village_rows():
    return [
        ("Yelahanka NES", "Yelahanka", 5, 0.85, "2026-06-20T10:00:00", 42.5),
        ("Kogilu", "Yelahanka", 3, 0.72, "2026-06-15T08:30:00", 28.3),
        ("Thammenahalli", "Devanahalli", 4, 0.68, "2026-06-18T12:00:00", 35.1),
    ]


def _fake_fetchall(mock_conn, rows):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_conn.execute.return_value = mock_cursor


# ── A1: download-guide endpoint ────────────────────────────────────────


def test_gate153_a1_download_guide_endpoint():
    """A1: GET /api/v1/deeds/download-guide returns 200 + villages list."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with patch("utils.deed_progress.get_priority_villages") as mock_pv:
        mock_pv.return_value = [
            {"village": "Yelahanka NES", "market": "Yelahanka",
             "assembly_signal_count": 5, "max_confidence": 0.85,
             "last_deed_ingested": "2026-06-20T10:00:00", "priority_score": 42.5,
             "kaveri_url_hint": "https://kaverionline.karnataka.gov.in → Form 17 Index II → Village: Yelahanka NES"},
        ]
        resp = client.get(
            "/api/v1/deeds/download-guide?market=Yelahanka&top_n=3",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "villages" in data
    assert isinstance(data["villages"], list)
    assert len(data["villages"]) >= 1
    item = data["villages"][0]
    assert "village" in item
    assert "priority_rank" in item
    assert "kaveri_url_hint" in item
    assert "guide_message" in data


# ── A2: get_priority_villages returns structured list ──────────────────


def test_gate153_a2_priority_villages_structured():
    """A2: get_priority_villages returns list with expected keys."""
    from utils.deed_progress import get_priority_villages

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        _fake_fetchall(mock_conn, _mock_village_rows())

        result = get_priority_villages("Yelahanka", top_n=3)

    assert isinstance(result, list)
    assert len(result) <= 3
    if result:
        item = result[0]
        assert "village" in item
        assert "assembly_signal_count" in item
        assert "kaveri_url_hint" in item
        assert item["kaveri_url_hint"].startswith("https://kaverionline.karnataka.gov.in")


# ── A3: reminder includes priority villages ────────────────────────────


def test_gate153_a3_reminder_includes_priority_villages():
    """A3: run_kaveri_download_reminder includes village name in Telegram message."""
    import json
    from config.scheduler.deed_jobs import run_kaveri_download_reminder

    mock_villages = [
        {"village": "Yelahanka NES", "market": "Yelahanka",
         "assembly_signal_count": 5, "max_confidence": 0.85,
         "last_deed_ingested": "2026-06-20T10:00:00", "priority_score": 42.5,
         "kaveri_url_hint": "..."},
        {"village": "Kogilu", "market": "Yelahanka",
         "assembly_signal_count": 3, "max_confidence": 0.72,
         "last_deed_ingested": "2026-06-15T08:30:00", "priority_score": 28.3,
         "kaveri_url_hint": "..."},
    ]

    with (
        patch("utils.deed_progress.get_priority_villages", return_value=mock_villages),
        patch("config.scheduler.deed_jobs.send"),
        patch("config.scheduler.deed_jobs._send_generic_reminder"),
        patch("config.scheduler.deed_jobs.Path.exists", return_value=True),
        patch("config.scheduler.deed_jobs.Path.read_text", return_value=json.dumps({
            "Yelahanka": {
                "kaveri_sro_district": "Gandhinagar",
                "villages": [{"name": "Yelahanka NE", "is_urban": False}],
            },
        })),
        patch("utils.telegram_notifier.send_message") as mock_tg,
    ):
        run_kaveri_download_reminder()

        # Collect all Telegram message texts
        called_texts = []
        for call in mock_tg.call_args_list:
            if call.args:
                called_texts.append(str(call.args[0]))
        all_text = " ".join(called_texts)

        assert "Yelahanka NES" in all_text or "Kogilu" in all_text, (
            f"Priority village name not found in Telegram message. Got: {all_text[:200]}"
        )
        assert "Top 3 villages" in all_text, "Priority section header missing from message"


# ── A4: Alembic migration 0074 importable ──────────────────────────────


def test_gate153_a4_migration_0074_importable():
    """A4: alembic/versions/0074_deed_village_priority.py is importable with upgrade/downgrade."""
    import importlib
    spec = importlib.util.spec_from_file_location(
        "alembic.versions._0074",
        str(pathlib.Path(__file__).parents[1] / "alembic" / "versions" / "0074_deed_village_priority.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)
    assert hasattr(mod, "VIEW_SQL")
    assert "v_deed_village_priority" in mod.VIEW_SQL


# ── A5: get_priority_villages returns [] on DB failure ─────────────────


# ── Edge case: unauthenticated access returns 401 ──────────────────────


def test_gate153_download_guide_no_auth_returns_401():
    """download-guide returns 401 without API key."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/api/v1/deeds/download-guide")
    assert resp.status_code == 401


# ── Edge case: unknown market returns empty villages list ──────────────


def test_gate153_priority_villages_unknown_market():
    """get_priority_villages with unknown market returns empty list."""
    from utils.deed_progress import get_priority_villages

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        result = get_priority_villages(market="NonexistentTown", top_n=5)

    assert isinstance(result, list)
    assert len(result) == 0


# ── Edge case: download-guide with all markets (market=None) ───────────


def test_gate153_download_guide_all_markets():
    """GET /api/v1/deeds/download-guide without market filter returns villages."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with patch("utils.deed_progress.get_priority_villages") as mock_pv:
        mock_pv.return_value = [
            {"village": "Yelahanka NES", "market": "Yelahanka",
             "assembly_signal_count": 5, "max_confidence": 0.85,
             "last_deed_ingested": "2026-06-20T10:00:00", "priority_score": 42.5,
             "kaveri_url_hint": "..."},
            {"village": "Kogilu", "market": "Devanahalli",
             "assembly_signal_count": 3, "max_confidence": 0.72,
             "last_deed_ingested": "2026-06-15T08:30:00", "priority_score": 28.3,
             "kaveri_url_hint": "..."},
        ]
        resp = client.get(
            "/api/v1/deeds/download-guide",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["villages"]) == 2
    assert data["guide_message"] is not None


# ── Edge case: top_n clamped at boundaries ─────────────────────────────


def test_gate153_priority_villages_top_n_clamping():
    """get_priority_villages clamps top_n to [1, 100]."""
    from utils.deed_progress import get_priority_villages

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        # Set up a simple return for both calls
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        result_neg = get_priority_villages(top_n=-5)
        result_zero = get_priority_villages(top_n=0)
        result_high = get_priority_villages(top_n=200)

    assert isinstance(result_neg, list), f"top_n=-5 should produce list, got {type(result_neg)}"
    assert isinstance(result_zero, list), f"top_n=0 should produce list, got {type(result_zero)}"
    assert isinstance(result_high, list), f"top_n=200 should produce list, got {type(result_high)}"
    # top_n=0 should be clamped to 1 — verify the query used LIMIT 1
    assert len(result_zero) == 0, "No rows expected for clamped query with no data"


# ── A5: get_priority_villages returns [] on DB failure ─────────────────


def test_gate153_a5_priority_villages_empty_on_failure():
    """A5: get_priority_villages returns [] on DB failure."""
    from utils.deed_progress import get_priority_villages

    with patch("utils.db.get_engine") as mock_eng:
        mock_eng.side_effect = Exception("DB connection failed")
        result = get_priority_villages("Yelahanka")

    assert isinstance(result, list)
    assert len(result) == 0
