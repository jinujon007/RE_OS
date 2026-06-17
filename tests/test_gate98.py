"""GATE-98: mypy clean, CI type-check blocking, core imports."""
import subprocess
import pytest

pytestmark = pytest.mark.unit

_SCOPE = ["agents/", "config/", "crews/", "utils/", "intelligence/", "ingest/"]
_FLAGS = [
    "--ignore-missing-imports",
    "--no-strict-optional",
    "--follow-imports=skip",
]


def test_mypy_exits_clean():
    result = subprocess.run(
        ["python", "-m", "mypy", *_SCOPE, *_FLAGS],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"mypy exit code {result.returncode} (expected 0)\n"
        f"stdout[-2000:]: {result.stdout[-2000:]}"
    )


def test_mypy_scope_matches_ci():
    lines = open(".github/workflows/ci.yml").readlines()
    in_block = False
    mypy_lines = []
    for line in lines:
        stripped = line.rstrip("\n")
        if stripped.rstrip() == "  type-check:":
            in_block = True
        if in_block:
            mypy_lines.append(stripped)
            if (
                len(mypy_lines) > 1
                and stripped.startswith("  ")
                and not stripped.startswith("    ")
                and stripped.rstrip().endswith(":")
                and "type-check" not in stripped
            ):
                mypy_lines.pop()
                break
    type_check_block = "\n".join(mypy_lines)
    assert "continue-on-error" not in type_check_block
    # CI must include crews/ — same scope as test
    assert "crews/" in type_check_block, "CI mypy missing crews/"


def test_core_imports():
    from config.scheduler import start_scheduler
    from dashboard.state import VALID_MARKETS
    from dashboard.routers.health import router
    assert callable(start_scheduler)
    assert "Yelahanka" in VALID_MARKETS
    assert router is not None

