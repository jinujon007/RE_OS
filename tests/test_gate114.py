"""GATE-114 — API Spec Automation declaration tests.

Verifies all deliverables from T-1256 -> T-1259:
1. scripts/export_openapi.py is importable and exposes get_schema()/main()
2. --dry-run exits 0 with valid JSON containing openapi + paths keys
3. CI workflow has api-spec-drift job name string
4. docs/api-changelog.md exists with version heading
5. Makefile has spec target

These are gate assertions — they test that the infrastructure is wired,
not the script's internal logic (which is tested in test_export_openapi.py).
"""
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "export_openapi.py"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CHANGELOG_PATH = REPO_ROOT / "docs" / "api-changelog.md"
MAKEFILE_PATH = REPO_ROOT / "Makefile"


@contextmanager
def _repo_root_on_path():
    sys.path.insert(0, str(REPO_ROOT))
    try:
        yield
    finally:
        sys.path.pop(0)


def test_export_openapi_script_importable():
    """scripts/export_openapi.py imports without error and exposes public API."""
    with _repo_root_on_path():
        import importlib
        mod = importlib.import_module("scripts.export_openapi")
        assert hasattr(mod, "get_schema")
        assert hasattr(mod, "main")
        assert hasattr(mod, "_validate_schema")


def test_dry_run_exits_zero_and_produces_valid_openapi_json():
    """--dry-run exits 0 and output is parseable OpenAPI JSON with required keys."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--dry-run"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"dry-run failed (exit {result.returncode}):\n"
        f"  stderr: {result.stderr[:500]}"
    )
    assert result.stdout.strip(), "dry-run produced no output"
    parsed = json.loads(result.stdout)
    assert "openapi" in parsed, "Missing 'openapi' key in generated spec"
    assert "paths" in parsed, "Missing 'paths' key in generated spec"
    assert "x-generated-at" in parsed, "Missing 'x-generated-at' timestamp"


def test_dry_run_help_flag_exits_zero():
    """--help prints usage and exits 0."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout or "usage:" in result.stdout.lower()


def test_ci_workflow_has_api_spec_drift_job():
    """CI workflow YAML defines api-spec-drift job."""
    assert CI_PATH.is_file(), f"CI file not found at {CI_PATH}"
    content = CI_PATH.read_text(encoding="utf-8")
    assert "api-spec-drift" in content, (
        "CI workflow must contain 'api-spec-drift' job"
    )


def test_api_changelog_exists():
    """docs/api-changelog.md exists with version heading and Added section."""
    assert CHANGELOG_PATH.is_file(), "docs/api-changelog.md not found"
    content = CHANGELOG_PATH.read_text(encoding="utf-8")
    assert "## v1." in content, "Changelog must have at least one version heading"
    assert "### Added" in content, "Changelog must have an Added section"


def test_makefile_has_spec_target():
    """Makefile has spec target for regenerating the OpenAPI spec."""
    assert MAKEFILE_PATH.is_file(), "Makefile not found"
    content = MAKEFILE_PATH.read_text(encoding="utf-8")
    assert "spec:" in content, "Makefile must define 'spec:' target"
