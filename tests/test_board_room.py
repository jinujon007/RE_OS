"""
T-301 — Board Room smoke tests.

Uses mocks for all external dependencies (DB, LLM, dept heads).
No live database or LLM calls.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── run_board_session ──────────────────────────────────────────────────────────

MOCK_DEPT_RESPONSES = {
    "bd": "GO — Yelahanka absorption rate strong at 68%. Three risks: delayed possession, oversupply Grade C. Recommended entry PSF: 6,200.",
    "finance": "VIABLE — Break-even PSF ₹5,800. IRR range 18–24% base/bull. Recommend 60:40 equity/debt.",
    "engineering": "FEASIBLE — BDA approval required. Construction cost ₹2,200/sqft. Timeline: 18 months to RERA registration.",
    "ops": "Channel mix: 60% CP / 25% direct / 15% digital. Velocity: 12 units/quarter. Launch Q3 2026.",
    "legal": "CLEAR — RERA registered, BDA approved, clear title, no encumbrances, agricultural conversion done, no regulatory overlays.",
}


@pytest.fixture
def patched_board():
    """Patch all board room external calls."""
    with (
        patch("crews.board_room._run_dept_heads", return_value=MOCK_DEPT_RESPONSES),
        patch("crews.board_room._create_session_row", return_value=True),
        patch("crews.board_room._update_session_row", return_value=True),
        patch(
            "crews.board_room._ceo_decompose",
            return_value={
                "bd": "Assess Yelahanka market absorption and entry PSF",
                "finance": "Calculate break-even PSF and IRR for Yelahanka entry",
                "engineering": "Identify approval blockers and construction cost risk",
                "ops": "Recommend channel mix and launch KPIs",
                "legal": "Evaluate RERA compliance and title risk for Yelahanka entry",
            },
        ),
        patch(
            "crews.board_room._extract_actions",
            return_value=[
                {
                    "action": "Acquire land in Yelahanka North",
                    "owner": "bd",
                    "priority": "high",
                },
            ],
        ),
    ):
        yield


def test_run_board_session_returns_session_id(patched_board):
    from crews.board_room import run_board_session

    result = run_board_session("Should LLS enter Yelahanka at PSF 6500?", "Yelahanka")
    assert "session_id" in result
    # Must be a valid UUID
    uuid.UUID(result["session_id"])


def test_run_board_session_status_pending(patched_board):
    from crews.board_room import run_board_session

    result = run_board_session("Should LLS enter Yelahanka at PSF 6500?", "Yelahanka")
    assert result["status"] == "pending"


def test_run_board_session_market_preserved(patched_board):
    from crews.board_room import run_board_session

    result = run_board_session("Should LLS enter Yelahanka at PSF 6500?", "Yelahanka")
    assert result["market"] == "Yelahanka"


def test_run_board_session_devanahalli(patched_board):
    from crews.board_room import run_board_session

    result = run_board_session("Enter Devanahalli at 5800 PSF?", "Devanahalli")
    assert result["status"] == "pending"
    assert result["market"] == "Devanahalli"


def test_run_board_session_db_failure_returns_error():
    """If DB row creation fails, result has status error."""
    with patch("crews.board_room._create_session_row", return_value=False):
        from crews.board_room import run_board_session

        result = run_board_session("test pitch", "Yelahanka")
    assert result["status"] == "error"
    assert "session_id" in result


# ── get_board_session ──────────────────────────────────────────────────────────


def test_get_board_session_returns_none_for_missing(monkeypatch):
    """Non-existent session_id → None."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.mappings.return_value.fetchone.return_value = None
    mock_engine.connect.return_value = mock_conn

    with patch("crews.board_room.get_engine", return_value=mock_engine):
        from crews.board_room import get_board_session

        result = get_board_session("00000000-0000-0000-0000-000000000000")
    assert result is None


def test_get_board_session_returns_all_fields(monkeypatch):
    """When DB returns a row, get_board_session maps all fields by column name."""
    session_id = str(uuid.uuid4())
    # Matches actual board_sessions schema (individual dept columns, not JSONB transcript)
    fake_row = {
        "session_id": session_id,
        "pitch_text": "Enter Yelahanka?",
        "market": "Yelahanka",
        "status": "complete",
        "bd_response": "GO — strong absorption",
        "finance_response": "VIABLE — IRR 22%",
        "engineering_response": "FEASIBLE — BDA needed",
        "ops_response": "45% CP mix",
        "legal_response": "CLEAR — RERA registered, BDA approved, clear title, no encumbrances.",
        "ceo_synthesis": None,
        "created_at": "2026-05-29 06:00:00",
        "completed_at": "2026-05-29 06:01:30",
        "response_time_s": 0.5,
    }
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.mappings.return_value.fetchone.return_value = (
        fake_row
    )
    mock_engine.connect.return_value = mock_conn

    with patch("crews.board_room.get_engine", return_value=mock_engine):
        from crews.board_room import get_board_session

        result = get_board_session(session_id)

    assert result["session_id"] == session_id
    assert result["status"] == "complete"
    assert result["market"] == "Yelahanka"
    assert result["pitch"] == "Enter Yelahanka?"  # mapped from pitch_text column
    assert result["completed_at"] == "2026-05-29 06:01:30"
    assert "responses" in result["transcript"]
    assert result["transcript"]["responses"]["bd"] == "GO — strong absorption"
    assert (
        result["transcript"]["responses"]["legal"]
        == "CLEAR — RERA registered, BDA approved, clear title, no encumbrances."
    )


# ── dept-head task templates ───────────────────────────────────────────────────


def test_dept_task_templates_all_five_keys():
    from crews.board_room import _DEPT_TASK_TEMPLATES

    for key in ("bd", "finance", "engineering", "ops", "legal"):
        assert key in _DEPT_TASK_TEMPLATES
        assert "{market}" in _DEPT_TASK_TEMPLATES[key]
        assert "{dept_question}" in _DEPT_TASK_TEMPLATES[key]


def test_bd_template_requires_go_nogo():
    from crews.board_room import _DEPT_TASK_TEMPLATES

    assert "GO / NO-GO" in _DEPT_TASK_TEMPLATES["bd"]


def test_finance_template_requires_viable():
    from crews.board_room import _DEPT_TASK_TEMPLATES

    assert "VIABLE" in _DEPT_TASK_TEMPLATES["finance"]


def test_engineering_template_requires_feasible():
    from crews.board_room import _DEPT_TASK_TEMPLATES

    assert "FEASIBLE" in _DEPT_TASK_TEMPLATES["engineering"]


def test_ops_template_requires_channel_mix():
    from crews.board_room import _DEPT_TASK_TEMPLATES

    assert "channel mix" in _DEPT_TASK_TEMPLATES["ops"].lower()


# ── T-1071: GV source + freshness in Finance Head context (GATE-78) ──────────


def _make_gv_mock_conn(gv_row: tuple | None = None):
    """Create a mock DB connection that returns a GV row for guidance_values query."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    def _mock_execute(*args, **kwargs):
        sql = args[0] if args else kwargs.get("statement", "")
        sql_str = str(sql) if hasattr(sql, "__str__") else str(sql)
        result = MagicMock()
        if "guidance_values" in sql_str and "gv" in sql_str.lower():
            result.fetchone.return_value = gv_row
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
        return result

    mock_conn.execute.side_effect = _mock_execute
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    return mock_engine


def test_board_room_finance_head_receives_gv_source_string():
    """Finance Head task description contains 'GUIDANCE VALUE SOURCE' string."""
    gv_row = ("gazette_pdf", 2024, 0.85, 5200.0)
    mock_engine = _make_gv_mock_conn(gv_row)

    captured_tasks = []

    class MockCrew:
        def __init__(self, *args, **kwargs):
            self.tasks = kwargs.get("tasks", [])

        def kickoff(self):
            return MagicMock()

    captured_tasks = []

    with (
        patch("utils.db.get_engine", return_value=mock_engine),
        patch("crews.board_room.get_engine", return_value=mock_engine),
        patch(
            "crews.board_room._DEPT_TASK_TEMPLATES",
            {
                "finance": "Market: {market}\n{dept_question}",
            },
        ),
        patch(
            "crews.board_room._extract_pitch_params",
            return_value={
                "area_sqft": None,
                "psf": None,
                "acreage": None,
            },
        ),
        patch("utils.psf_forecaster.PSFForecaster", return_value=MagicMock()),
        patch("utils.irr_model.GDVEstimator"),
        patch("utils.irr_model.compare_scenarios"),
        patch("crews.board_room._query_market_supply", return_value=(None, "N/A")),
        patch(
            "crewai.Task",
            side_effect=lambda *a, **kw: (captured_tasks.append(kw), MagicMock())[1],
        ),
    ):
        from crews.board_room import _run_dept_heads

        result = _run_dept_heads(
            pitch="5 acres Yelahanka",
            market="Yelahanka",
            decomposition={"finance": "Calculate IRR for Yelahanka"},
        )

    task_descriptions = [t.get("description", "") for t in captured_tasks]
    all_text = " ".join(task_descriptions)
    assert "GUIDANCE VALUE SOURCE" in all_text, (
        f"GV source string not found in task descriptions: {task_descriptions}"
    )


def test_board_room_flags_stale_gv_when_over_18_months():
    """Finance Head context warns when GV is stale (>18 months)."""
    gv_row = ("gazette_pdf", 2022, 0.70, 4500.0)
    mock_engine = _make_gv_mock_conn(gv_row)

    captured_tasks = []

    with (
        patch("utils.db.get_engine", return_value=mock_engine),
        patch("crews.board_room.get_engine", return_value=mock_engine),
        patch(
            "crews.board_room._DEPT_TASK_TEMPLATES",
            {
                "finance": "Market: {market}\n{dept_question}",
            },
        ),
        patch(
            "crews.board_room._extract_pitch_params",
            return_value={
                "area_sqft": None,
                "psf": None,
                "acreage": None,
            },
        ),
        patch("utils.psf_forecaster.PSFForecaster", return_value=MagicMock()),
        patch("utils.irr_model.GDVEstimator"),
        patch("utils.irr_model.compare_scenarios"),
        patch("crews.board_room._query_market_supply", return_value=(None, "N/A")),
        patch(
            "crewai.Task",
            side_effect=lambda *a, **kw: (captured_tasks.append(kw), MagicMock())[1],
        ),
    ):
        from crews.board_room import _run_dept_heads

        result = _run_dept_heads(
            pitch="5 acres Yelahanka",
            market="Yelahanka",
            decomposition={"finance": "Calculate IRR for Yelahanka"},
        )

    task_descriptions = [t.get("description", "") for t in captured_tasks]
    all_text = " ".join(task_descriptions)
    assert "GUIDANCE VALUE SOURCE" in all_text
    # Stale GV (2022) should produce a warning
    assert any("WARNING" in d or "stale" in d.lower() for d in task_descriptions), (
        "No stale GV warning found in task descriptions"
    )
