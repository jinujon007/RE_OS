"""Unit tests for scripts/export_openapi.py (T-1256, T-1257).

These test the script's core functions directly via import.
The end-to-end subprocess --dry-run behavior is tested in test_gate114.py
to avoid duplication.
"""
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "export_openapi.py"


@contextmanager
def _repo_root_on_path():
    sys.path.insert(0, str(REPO_ROOT))
    try:
        yield
    finally:
        sys.path.pop(0)


def test_export_openapi_script_exists():
    assert SCRIPT_PATH.is_file(), f"Script not found at {SCRIPT_PATH}"


def test_openapi_schema_has_x_generated_at():
    with _repo_root_on_path():
        from scripts.export_openapi import get_schema, _validate_schema
        schema = get_schema()
        assert "x-generated-at" in schema
        assert "openapi" in schema
        assert "paths" in schema
        assert len(_validate_schema(schema)) == 0


def test_openapi_schema_validation_rejects_missing_keys():
    with _repo_root_on_path():
        from scripts.export_openapi import _validate_schema
        errors = _validate_schema({"info": {}})
        assert any("openapi" in e for e in errors)
        assert any("paths" in e for e in errors)


def test_export_openapi_dry_run_flag():
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--dry-run"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"dry-run stderr: {result.stderr}"
    assert result.stdout.strip(), "dry-run produced no output"
    import json
    parsed = json.loads(result.stdout)
    assert "openapi" in parsed
    assert "paths" in parsed
    assert "x-generated-at" in parsed
