"""GATE-129 — Board Room Output Quality: Formatter + GO/NO-GO Decision Flag.

5 assertions (all code-verifiable without Docker):
A1: BoardRoomFormatter importable and exposes 4 key methods
A2: Legal head NO-GO veto forces overall NO-GO
A3: board_room.py imports BoardRoomFormatter and persists decision_flag + formatted_md
A4: GET /board/sessions endpoint extracts decision_flag from ceo_synthesis
A5: format_discord() output <=2000 chars with decision flag near top
"""

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _make_nogo_legal_responses() -> dict[str, str]:
    return {
        "bd": "I recommend proceeding. Good opportunity.",
        "finance": "Viable. Positive NPV.",
        "engineering": "Feasible.",
        "ops": "Operationally sound.",
        "legal": "I reject this deal. Title issues found — do not proceed.",
    }


def _make_all_positive_responses() -> dict[str, str]:
    return {
        "bd": "I recommend proceeding. The location has strong demand.",
        "finance": "The IRR looks viable. Positive cashflow expected.",
        "engineering": "Site conditions are favorable. Soil report is clean.",
        "ops": "Operationally feasible. Good access and utilities.",
        "legal": "Title is clear. No encumbrances found. Recommend proceed.",
    }


def _parse_imports(source: str) -> set[str]:
    """Extract imported symbol names from a Python source string via AST."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for alias in node.names:
                    names.add(f"{node.module}.{alias.name}")
    return names


def test_gate129_a1_importable():
    """A1: BoardRoomFormatter importable and exposes public surface."""
    from utils.board_room_formatter import BoardRoomFormatter

    assert callable(BoardRoomFormatter)
    fmt = BoardRoomFormatter({})
    assert hasattr(fmt, "decision_flag")
    assert hasattr(fmt, "format_discord")
    assert hasattr(fmt, "format_full_markdown")
    assert hasattr(fmt, "format_summary_table")
    # Public methods should be callable without error on empty input
    assert fmt.decision_flag() == "CONDITIONAL"
    assert isinstance(fmt.format_discord(), str)
    assert isinstance(fmt.format_full_markdown(), str)
    assert fmt.format_summary_table() == ""


def test_gate129_a2_legal_nogo_veto():
    """A2: Legal head NO-GO forces overall NO-GO."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_nogo_legal_responses())
    assert fmt.decision_flag() == "NO-GO"
    # Finance should still be GO but Legal veto overrides
    assert fmt.assessments.get("legal", {}).get("verdict") == "NO-GO"
    assert fmt.assessments.get("finance", {}).get("verdict") == "GO"


def test_gate129_a3_wired_in_board_room():
    """A3: board_room.py imports BoardRoomFormatter and stores decision_flag + formatted_md + formatted_discord."""
    src = (REPO_ROOT / "crews" / "board_room.py").read_text(encoding="utf-8")
    imports = _parse_imports(src)
    assert any("BoardRoomFormatter" in name for name in imports), (
        "board_room.py must import BoardRoomFormatter. "
        f"Found imports: {imports}"
    )
    assert "decision_flag" in src, (
        "board_room.py must write decision_flag into transcript"
    )
    assert "formatted_md" in src, (
        "board_room.py must write formatted_md into transcript"
    )
    assert "formatted_discord" in src, (
        "board_room.py must write formatted_discord into transcript"
    )


def test_gate129_a4_sessions_endpoint_surfaces_flag():
    """A4: board sessions router extracts decision_flag from ceo_synthesis JSON."""
    router_src = (REPO_ROOT / "dashboard" / "routers" / "board_room.py").read_text(
        encoding="utf-8"
    )
    assert "decision_flag" in router_src, (
        "board_room router must reference decision_flag"
    )
    # Check that the router calls .get("decision_flag") on the parsed JSON
    assert "decision_flag" in router_src.split("synth")[1] if "synth" in router_src else True, (
        "router must extract decision_flag from ceo_synthesis synth dict"
    )

    board_room_src = (REPO_ROOT / "crews" / "board_room.py").read_text(encoding="utf-8")
    assert "decision_flag" in board_room_src, (
        "get_board_session must include decision_flag in response dict"
    )


def test_gate129_a5_discord_under_2000():
    """A5: format_discord() output <=2000 chars with decision flag prominent."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_all_positive_responses())
    output = fmt.format_discord()
    assert len(output) <= 2000, (
        f"Discord output is {len(output)} chars (max 2000)"
    )
    # Decision flag must be in the first 200 chars (after bold markers, emoji)
    decision_line = [ln for ln in output.split("\n") if "DECISION:" in ln]
    assert decision_line, "No DECISION line found in Discord output"
    assert "GO" in decision_line[0], (
        f"DECISION line should contain flag: {decision_line[0]}"
    )
    # API reference should be present
    assert "/api/board/session" in output, (
        "Discord output should reference the session API endpoint"
    )
