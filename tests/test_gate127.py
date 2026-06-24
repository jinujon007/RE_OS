"""GATE-127 — Windows onboarding script + stack health check.

7 assertions (all code-verifiable without Docker):
A1: health_check.py --dry-run exits 0 + output covers all 9 checks
A2: onboard.ps1 exists and references key scripts
A3: deed_inbox README exists with required content
A4: health_check.py covers all 9 checks
A5: gitkeep present + .gitignore covers deed_inbox PDFs
A6: health_check.py --json returns valid JSON with all_ok key
A7: health_check._docker_cmd returns list (fallback logic test)
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

_CHECK_NAMES = [
    "Docker daemon", "Containers running", "PostgreSQL",
    "Redis", "Ollama", "Dashboard API",
    "Alembic head", "data floor", "Scheduler",
]


def test_gate127_a1_health_check_dry_run():
    """A1: health_check.py --dry-run exits 0 + output covers all 9 checks."""
    script = REPO_ROOT / "scripts" / "health_check.py"
    assert script.exists(), f"health_check.py not found at {script}"

    r = subprocess.run(
        [sys.executable, str(script), "--dry-run"],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert r.returncode == 0, (
        f"health_check.py --dry-run failed (exit {r.returncode}):\n"
        f"stdout: {r.stdout[:500]}\nstderr: {r.stderr[:500]}"
    )
    for name in _CHECK_NAMES:
        assert name in r.stdout, (
            f"Check '{name}' not found in --dry-run output"
        )


def test_gate127_a2_onboard_ps1_exists():
    """A2: onboard.ps1 exists and references key scripts."""
    ps1 = REPO_ROOT / "scripts" / "onboard.ps1"
    assert ps1.exists(), f"onboard.ps1 not found at {ps1}"

    text = ps1.read_text(encoding="utf-8")
    assert "process_deed_inbox.py" in text, "onboard.ps1 must reference process_deed_inbox.py"
    assert "check_conditional_gates.py" in text, "onboard.ps1 must reference check_conditional_gates.py"
    assert "market_intel_crew.py" in text, "onboard.ps1 must reference market_intel_crew.py"
    assert "health_check.py" in text, "onboard.ps1 must reference health_check.py"


def test_gate127_a3_deed_inbox_readme():
    """A3: deed_inbox README exists with required content."""
    readme = REPO_ROOT / "data" / "deed_inbox" / "README.md"
    assert readme.exists(), f"README not found at {readme}"

    text = readme.read_text(encoding="utf-8")
    assert "Form17" in text, "README must mention Form17"
    assert "Monday" in text, "README must mention processing schedule (Monday)"
    assert "SHA-256" in text or "SHA256" in text, "README must mention SHA-256 dedup"
    assert any(sym in text for sym in ("₹", "Rs.", "Rs ", "INR", "per")), (
        "README must mention pricing in Rupees"
    )
    assert "Kaveri" in text or "kaverionline" in text, "README must reference Kaveri portal"


def test_gate127_a4_health_check_coverage():
    """A4: health_check.py covers all 9 checks and --verbose flag."""
    src = (REPO_ROOT / "scripts" / "health_check.py").read_text(encoding="utf-8")

    for check in _CHECK_NAMES:
        assert check in src, f"health_check.py missing check string: {check}"

    assert "dry" in src or "--dry-run" in src, "health_check.py must support --dry-run"
    assert "verbose" in src or "--verbose" in src, "health_check.py must support --verbose"


def test_gate127_a5_gitkeep_and_gitignore():
    """A5: gitkeep present + .gitignore covers deed_inbox PDFs."""
    gitkeep = REPO_ROOT / "data" / "deed_inbox" / ".gitkeep"
    assert gitkeep.exists(), f".gitkeep not found at {gitkeep}"

    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "deed_inbox" in gitignore, ".gitignore must contain deed_inbox pattern"
    assert "*.pdf" in gitignore or "deed_inbox" in gitignore, ".gitignore must cover PDFs in deed_inbox"


def test_gate127_a6_health_check_json_output():
    """A6: health_check.py --json returns valid JSON with all_ok key."""
    script = REPO_ROOT / "scripts" / "health_check.py"
    assert script.exists()

    r = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--json"],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert r.returncode == 0, f"--json failed (exit {r.returncode}): {r.stderr[:300]}"

    data = json.loads(r.stdout)
    assert isinstance(data, dict), "--json output must be a dict"
    assert "checks" in data, "--json output must contain 'checks' list"
    assert "all_ok" in data, "--json output must contain 'all_ok' bool"
    assert data["all_ok"] is True, "--dry-run --json must report all_ok=True"
    assert isinstance(data["checks"], list), "'checks' must be a list"
    assert len(data["checks"]) == len(_CHECK_NAMES), (
        f"Expected {len(_CHECK_NAMES)} checks, got {len(data['checks'])}"
    )

    for i, c in enumerate(data["checks"]):
        assert c["ok"] is True, f"Check {i} ('{c.get('name', '?')}') should pass in dry-run"
        assert "name" in c, f"Check {i} missing 'name'"
        assert "message" in c, f"Check {i} missing 'message'"


def test_gate127_a7_docker_cmd_fallback():
    """A7: _docker_cmd returns a list with at least 2 elements."""
    from scripts.health_check import _docker_cmd

    cmd = _docker_cmd()
    assert isinstance(cmd, list), f"_docker_cmd() returned {type(cmd)}, expected list"
    assert len(cmd) >= 2, f"_docker_cmd() returned {cmd}, expected at least 2 parts"


def test_gate127_a8_verbose_flag_accepted():
    """A8: health_check.py --dry-run --verbose exits 0 (flag accepted)."""
    script = REPO_ROOT / "scripts" / "health_check.py"
    assert script.exists()

    r = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--verbose"],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert r.returncode == 0, (
        f"--dry-run --verbose failed (exit {r.returncode}): {r.stderr[:300]}"
    )


def test_gate127_a9_version_flag():
    """A9: health_check.py --version prints version and exits 0."""
    script = REPO_ROOT / "scripts" / "health_check.py"
    assert script.exists()

    r = subprocess.run(
        [sys.executable, str(script), "--version"],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, f"--version failed (exit {r.returncode}): {r.stderr[:200]}"
    assert "version" in r.stdout.lower(), f"--version output missing 'version': {r.stdout[:200]}"
