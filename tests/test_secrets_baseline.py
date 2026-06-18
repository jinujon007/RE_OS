"""Tests for secrets scan baseline — T-1226."""

import os


def test_secrets_baseline_file_exists():
    """Assert .secrets.baseline exists in repo root."""
    path = os.path.join(os.path.dirname(__file__), "..", ".secrets.baseline")
    assert os.path.exists(path), ".secrets.baseline not found"
    assert os.path.getsize(path) > 0, ".secrets.baseline is empty"
