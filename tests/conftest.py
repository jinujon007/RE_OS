"""
Pytest configuration — sets env vars and stubs heavy dependencies before any imports.
"""

import os
import sys
import types
from unittest.mock import MagicMock

# Required by config/settings.py — must be set before any module-level import
os.environ.setdefault("DB_PASSWORD", "test_password_for_pytest")

# Stub crewai so llm_router tests run without installing the full crewai stack.
# patch.multiple() inside each test replaces config.llm_router.LLM with a per-test mock.
if "crewai" not in sys.modules:
    _crewai_stub = types.ModuleType("crewai")
    _crewai_stub.LLM = MagicMock
    sys.modules["crewai"] = _crewai_stub
