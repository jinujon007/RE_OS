"""GATE-110 — mypy Strict Optional: 4 assertions + full 6-directory coverage."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
MYPY_INI = REPO_ROOT / "mypy.ini"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

_ALL_MYPY_DIRS = ["agents", "config", "crews", "utils", "intelligence", "ingest"]

# Run-sections in CI YAML — only these lines should be flag-free
_RUN_LINE = re.compile(r"^\s+run:")


def test_mypy_ini_exists():
    assert MYPY_INI.exists(), "mypy.ini not found at repo root"


def test_mypy_ini_no_strict_optional_disabled():
    content = MYPY_INI.read_text(encoding="utf-8")
    assert "no_strict_optional = True" not in content, (
        "mypy.ini must not contain 'no_strict_optional = True'"
    )


def _ci_run_section_lines() -> list[str]:
    """Extract lines belonging to CI `run:` blocks (active shell commands)."""
    if not CI_YML.exists():
        return []
    lines = CI_YML.read_text(encoding="utf-8").split("\n")
    inside_run = False
    run_lines: list[str] = []
    for line in lines:
        if _RUN_LINE.match(line):
            inside_run = True
            continue
        if inside_run:
            if line.strip() and not line.startswith(" ") and not line.startswith("\t"):
                inside_run = False
            else:
                # skip comment lines — they may mention removed flags in prose
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue
                run_lines.append(line)
    return run_lines


def test_ci_yml_no_strict_optional_flag_in_commands():
    run_lines = _ci_run_section_lines()
    if not run_lines:
        pytest.skip("CI workflow not found")
    flagged = [ln for ln in run_lines if "--no-strict-optional" in ln]
    assert len(flagged) == 0, (
        "CI run command contains --no-strict-optional: " + str(flagged)
    )


def test_ci_yml_no_ignore_missing_imports_flag_in_commands():
    run_lines = _ci_run_section_lines()
    if not run_lines:
        pytest.skip("CI workflow not found")
    flagged = [ln for ln in run_lines if "--ignore-missing-imports" in ln]
    assert len(flagged) == 0, (
        "CI run command contains --ignore-missing-imports: " + str(flagged)
    )


def test_mypy_all_six_dirs_exit_zero():
    """Run the EXACT CI command — all 6 directories together."""
    cmd = [
        sys.executable, "-m", "mypy",
        *[f"{d}/" for d in _ALL_MYPY_DIRS],
        "--config-file", str(MYPY_INI),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    assert result.returncode == 0, (
        f"mypy on all 6 dirs exits {result.returncode} — must exit 0\n{result.stdout}"
    )
