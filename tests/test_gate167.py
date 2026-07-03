"""GATE-167: Utils + Scraper + Scheduler coverage — 5 gate assertions (A1-A5).

A1: importlib.import_module("utils.deal_scorer") succeeds
A2: importlib.import_module("utils.board_room_formatter") succeeds + BoardRoomFormatter callable
A3: importlib.import_module("scrapers.kaveri_form17") succeeds
A4: importlib.import_module("scrapers.rera_karnataka") succeeds
A5: All 7 scheduler modules importable without exception

Design notes:
  - A2 checks BoardRoomFormatter (class), not format_board_verdict (function)
    as originally spec'd — the latter does not exist in the codebase.
  - A5 catches Exception (not just ImportError) because some scheduler modules
    may have import-time side effects (e.g. DB connections).
  - These 5 assertions are the gate contract, complementing the broader
    test_module_coverage.py which tests all 86 + 19 modules exhaustively.
  - Environment variables are set via setdefault to avoid overriding values
    already provided by pytest.ini or docker-compose environment.
"""

import importlib
import os

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")

pytestmark = [pytest.mark.unit]

SCHEDULER_MODULES = [
    "config.scheduler.maintenance_jobs",
    "config.scheduler.rera_jobs",
    "config.scheduler.kaveri_jobs",
    "config.scheduler.intel_jobs",
    "config.scheduler.digest_jobs",
    "config.scheduler.forecast_jobs",
    "config.scheduler.deed_jobs",
]


def test_gate167_a1_utils_deal_scorer():
    """A1: utils.deal_scorer module imports without error.

    deal_scorer is the core deal scoring engine used by Board Room and
    the deal-score API endpoint. A silent import failure here means
    every deal score calculation will fail at runtime.
    """
    importlib.import_module("utils.deal_scorer")


def test_gate167_a2_utils_board_room_formatter():
    """A2: utils.board_room_formatter imports + BoardRoomFormatter callable.

    BoardRoomFormatter formats verdicts from department head evaluations
    into Discord messages and markdown memos. The original spec listed
    format_board_verdict, but the actual public symbol is the
    BoardRoomFormatter class (which has format_discord, format_full_markdown
    etc. as instance methods).
    """
    mod = importlib.import_module("utils.board_room_formatter")
    assert hasattr(mod, "BoardRoomFormatter"), (
        "board_room_formatter missing BoardRoomFormatter. "
        f"Available: {[x for x in dir(mod) if not x.startswith('_')]}"
    )
    assert callable(mod.BoardRoomFormatter) or isinstance(mod.BoardRoomFormatter, type), (
        f"board_room_formatter.BoardRoomFormatter is "
        f"{type(mod.BoardRoomFormatter).__name__}, expected callable or class"
    )


def test_gate167_a3_scrapers_kaveri_form17():
    """A3: scrapers.kaveri_form17 module imports without error.

    kaveri_form17 parses Form 17 PDFs from Kaveri Online Services —
    the primary source of registered sale deed data. If this module
    fails to import, deed ingestion is completely broken.
    """
    importlib.import_module("scrapers.kaveri_form17")


def test_gate167_a4_scrapers_rera_karnataka():
    """A4: scrapers.rera_karnataka module imports without error.

    rera_karnataka scrapes RERA Karnataka for registered project data,
    completion status, and developer track record. A silent import
    failure means the RERA data pipeline is dark.
    """
    importlib.import_module("scrapers.rera_karnataka")


def test_gate167_a5_all_scheduler_modules():
    """A5: All 7 scheduler modules import without exception.

    The 7 scheduler modules drive deed ingestion, RERA updates, market
    intel, maintenance, forecasts, and investor digests. If any fails
    to import, its cron schedule will fire into a broken container,
    producing silent failures logged only at WARNING level.

    Expected modules:
      - maintenance_jobs, rera_jobs, kaveri_jobs, intel_jobs,
        digest_jobs, forecast_jobs, deed_jobs
    """
    failures: list[tuple[str, str]] = []
    for mod_path in SCHEDULER_MODULES:
        try:
            importlib.import_module(mod_path)
        except Exception as e:
            failures.append((mod_path, f"{type(e).__name__}: {e}"))
    assert not failures, (
        f"A5 FAIL: {len(failures)} scheduler import errors: {failures}"
    )
