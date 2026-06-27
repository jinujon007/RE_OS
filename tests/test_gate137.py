"""GATE-137 declaration: Decision Journal Workflow.

8 assertions:
1. create_entry importable, accepts signature (market, decision_flag, context_summary, board_session_id)
2. create_entry rejects empty market and invalid flag (returns -1 without DB call)
3. Board Room bg worker calls both create_entry + write_decision_journal_entry
4. write_decision_journal_entry importable and produces correct filename
5. GET /decision-journal registered in data router
6. GET /decision-journal/{entry_id} registered in data router
7. decision_flag field in entry schema, restricted to valid values
8. Migration 0068 adds correct columns
"""

import importlib
import inspect
from unittest.mock import patch, MagicMock


def test_create_entry_signature():
    from utils.decision_journal import create_entry
    sig = inspect.signature(create_entry)
    params = list(sig.parameters.keys())
    assert "market" in params
    assert "decision_flag" in params
    assert "context_summary" in params
    assert "board_session_id" in params
    # board_session_id must have default=None
    assert sig.parameters["board_session_id"].default is None


@patch("utils.decision_journal.get_engine")
def test_create_entry_rejects_empty_market(mock_get_engine):
    from utils.decision_journal import create_entry
    result = create_entry("", "GO", "test")
    assert result == -1
    mock_get_engine.assert_not_called()


@patch("utils.decision_journal.get_engine")
def test_create_entry_rejects_invalid_flag(mock_get_engine):
    from utils.decision_journal import create_entry
    result = create_entry("Yelahanka", "INVALID_FLAG", "test")
    assert result == -1
    mock_get_engine.assert_not_called()


def test_board_room_hooks_decision_journal():
    import crews.board_room as br
    source = open(br.__file__, encoding="utf-8").read()
    assert "from utils.decision_journal import create_entry" in source
    assert "from utils.obsidian_sync import write_decision_journal_entry" in source


def test_decision_journal_routes_registered():
    from dashboard.routers.data import router
    routes = [(r.path, list(r.methods)) for r in router.routes]
    matched = [r for r in routes if "decision-journal" in r[0]]
    assert len(matched) >= 2
    paths = {r[0] for r in matched}
    assert "/decision-journal" in paths
    assert any("{entry_id}" in p for p in paths)


def test_write_decision_journal_entry_signature():
    from utils.obsidian_sync import write_decision_journal_entry
    sig = inspect.signature(write_decision_journal_entry)
    assert "entry" in sig.parameters


@patch("utils.obsidian_sync._ensure_sync_dir")
@patch("utils.obsidian_sync._write_md")
def test_write_decision_journal_entry_filename(mock_write_md, mock_ensure):
    from utils.obsidian_sync import write_decision_journal_entry
    mock_ensure.return_value = True
    mock_write_md.return_value = "/fake/path/file.md"
    entry = {"market": "Yelahanka", "decision_flag": "GO", "context_summary": "test"}
    write_decision_journal_entry(entry)
    call_args = mock_write_md.call_args
    assert call_args is not None
    filename = call_args[0][0]
    assert "(AI)" in filename
    assert "Yelahanka" in filename
    assert "GO" in filename


def test_decision_flag_restricted():
    from utils.decision_journal import _VALID_FLAGS
    assert isinstance(_VALID_FLAGS, frozenset)
    assert _VALID_FLAGS == {"GO", "NO-GO", "CONDITIONAL", "NEUTRAL"}


def test_migration_0068_columns():
    import ast
    import os
    version_dir = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions")
    mig_file = os.path.join(version_dir, "0068_decision_journal_workflow.py")
    assert os.path.isfile(mig_file), "Migration 0068 file not found"
    with open(mig_file, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    add_column_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_column":
            if len(node.args) >= 2:
                col = node.args[1]
                if isinstance(col, ast.Call):
                    col_name = getattr(getattr(col, "func", None), "attr", None)
                    if col_name == "Column" and col.args:
                        if isinstance(col.args[0], ast.Constant):
                            add_column_calls.append(col.args[0].value)
    assert "decision_flag" in add_column_calls
    assert "context_summary" in add_column_calls
    assert "board_session_id" in add_column_calls
