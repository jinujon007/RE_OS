"""GATE-133 — Obsidian MCP: Pipeline Output to Vault.

5 assertions (all code-verifiable without Docker):
A1: obsidian_sync importable; all 3 write functions callable; __all__ present
A2: Frontmatter has type=crystallization, area=lls, ai_generated=true, status=active
A3: obsidian-export endpoint registered in board_room router
A4: (AI) filename prefix convention used by all write functions
A5: test_obsidian_sync.py suite passes (subprocess runner)
A6: _READ_ONLY_PREFIXES contains /api/v1/board/sessions/
"""

import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_gate133_a1_importable():
    from utils.obsidian_sync import (
        write_board_verdict, write_weekly_digest, write_psf_forecast, __all__,
    )
    assert callable(write_board_verdict)
    assert callable(write_weekly_digest)
    assert callable(write_psf_forecast)
    assert "write_board_verdict" in __all__
    assert "write_weekly_digest" in __all__
    assert "write_psf_forecast" in __all__


def test_gate133_a2_required_frontmatter(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", str(tmp_path))
    from utils.obsidian_sync import write_board_verdict, write_weekly_digest, write_psf_forecast

    path = write_board_verdict("Yelahanka", "test", "CONDITIONAL")
    assert path
    content = pathlib.Path(path).read_text(encoding="utf-8")
    assert "type: crystallization" in content
    assert "area: lls" in content
    assert "ai_generated: true" in content
    assert "status: active" in content

    path2 = write_weekly_digest("Devanahalli", "digest")
    content2 = pathlib.Path(path2).read_text(encoding="utf-8")
    assert "type: crystallization" in content2
    assert "status: active" in content2

    path3 = write_psf_forecast("Hebbal", {"trend_direction": "flat", "current_psf": 0})
    content3 = pathlib.Path(path3).read_text(encoding="utf-8")
    assert "type: crystallization" in content3
    assert "status: active" in content3


def test_gate133_a3_export_endpoint():
    router_src = (REPO_ROOT / "dashboard" / "routers" / "board_room.py").read_text(encoding="utf-8")
    assert "obsidian-export" in router_src
    assert "filename" in router_src
    assert "content" in router_src
    assert "frontmatter" in router_src


def test_gate133_a4_ai_filename_prefix(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_SYNC_PATH", str(tmp_path))
    from utils.obsidian_sync import write_board_verdict, write_weekly_digest, write_psf_forecast

    p1 = write_board_verdict("Yelahanka", "t", "GO")
    p2 = write_weekly_digest("Devanahalli", "t")
    p3 = write_psf_forecast("Hebbal", {"trend_direction": "flat", "current_psf": 0})
    for p in [p1, p2, p3]:
        assert p, "write function returned empty path"
        name = pathlib.Path(p).name
        assert name.startswith("(AI)"), f"Filename should start with (AI): {name}"


def test_gate133_a5_obsidian_tests_pass():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header",
         str(pathlib.Path("tests/test_obsidian_sync.py"))],
        capture_output=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"obsidian_sync tests failed (exit {result.returncode})\n"
        f"{result.stderr.decode()[:500]}"
    )


def test_gate133_a6_read_only_prefix():
    state_src = (REPO_ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert "/api/v1/board/sessions/" in state_src, \
        "state.py must include /api/v1/board/sessions/ in _READ_ONLY_PREFIXES"
