"""Per-directory mypy check — T-1239, T-1240.

These run mypy on individual directories as a fast development feedback loop.
The authoritative gate-level check is test_gate110::test_mypy_all_six_dirs_exit_zero
which runs the exact CI command (all 6 dirs together with import resolution).

NOTE: Per-directory checks use mypy's follow_imports=skip default from mypy.ini.
This means imported names from other directories resolve as Any, masking some
type errors that only appear in the combined 6-directory CI run. Always run
the combined check before declaring GATE-110 green.
"""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
MYPY_CONFIG = REPO_ROOT / "mypy.ini"

_MYPY_TARGETS: list[tuple[str, str]] = [
    ("agents/", "agents"),
    ("intelligence/", "intelligence"),
    ("ingest/", "ingest"),
    ("config/", "config"),
    # NOTE: crews/ and utils/ excluded because they import typed symbols from
    # other dirs that resolve via follow_imports=skip. Their errors only surface
    # in the combined 6-directory check. See test_gate110::test_mypy_all_six_dirs_exit_zero.
]


@pytest.mark.parametrize("target,label", _MYPY_TARGETS, ids=[t[1] for t in _MYPY_TARGETS])
def test_mypy_dir_zero_errors(target: str, label: str):
    result = subprocess.run(
        [sys.executable, "-m", "mypy", target, "--config-file", str(MYPY_CONFIG)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    assert result.returncode == 0, (
        f"mypy {target} exits {result.returncode}:\n{result.stdout}"
    )
