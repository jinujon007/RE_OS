"""GATE-104 — Integration Test Baseline declaration.

5 unit-safe assertions:
1. tests/conftest.py contains live_engine fixture definition + docker_available helper
2. tests/test_integration_core.py exists with ≥5 test functions
3. CI workflow file contains zero --ignore flags (any file)
4. pytest.mark.integration is registered (no PytestUnknownMarkWarning)
5. tests/test_live_engine_basic.py exists with ≥2 test functions
"""

from pathlib import Path
import re

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
CI_YML = REPO / ".github" / "workflows" / "ci.yml"

_IGNORE_RE = re.compile(r"--ignore=")


def test_a1_conftest_has_live_engine():
    """A1: conftest.py contains live_engine fixture + docker_available."""
    conftest = REPO / "tests" / "conftest.py"
    assert conftest.exists(), "tests/conftest.py does not exist"
    content = conftest.read_text(encoding="utf-8")
    assert "def live_engine" in content, (
        "conftest.py does not define live_engine fixture"
    )
    assert "_docker_available" in content, (
        "conftest.py does not define _docker_available guard"
    )
    assert "config.settings" in content, (
        "conftest.py does not update config.settings.DATABASE_URL"
    )


def _count_test_functions(filepath: Path) -> int:
    content = filepath.read_text(encoding="utf-8")
    return sum(1 for line in content.splitlines() if line.startswith("def test_"))


def test_a2_integration_core_has_5_tests():
    """A2: test_integration_core.py exists with ≥5 test functions."""
    core = REPO / "tests" / "test_integration_core.py"
    assert core.exists(), "tests/test_integration_core.py does not exist"
    assert _count_test_functions(core) >= 5


def test_a3_no_ignore_flags_in_ci():
    """A3: CI workflow contains zero --ignore flags (any file)."""
    assert CI_YML.exists(), f"CI workflow not found at {CI_YML}"
    content = CI_YML.read_text(encoding="utf-8")
    matches = _IGNORE_RE.findall(content)
    assert not matches, (
        f"CI workflow still contains {len(matches)} --ignore flag(s). "
        f"All must be removed and replaced with marker filters."
    )


def test_a4_integration_mark_registered():
    """A4: pytest.mark.integration is registered (no unknown-mark warning)."""
    ini = REPO / "pytest.ini"
    assert ini.exists(), "pytest.ini does not exist"
    content = ini.read_text(encoding="utf-8")
    assert "integration" in content, (
        "pytest.ini does not register the integration marker"
    )


def test_a5_live_engine_basic_tests_exist():
    """A5: test_live_engine_basic.py exists with ≥2 fixture tests."""
    basic = REPO / "tests" / "test_live_engine_basic.py"
    assert basic.exists(), "tests/test_live_engine_basic.py does not exist"
    assert _count_test_functions(basic) >= 2
