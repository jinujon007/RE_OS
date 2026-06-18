"""Shared test fixtures and helpers (R2)."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
"""Absolute path to repository root. All test files should use this instead
of computing their own parent chain."""
