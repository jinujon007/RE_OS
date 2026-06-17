"""GATE-96 — Scheduler Package Split declaration.
5 assertions: package import, re-exports, backward-compatible imports, start_scheduler.
"""
import pytest

pytestmark = pytest.mark.unit


def test_gate96_scheduler_is_package():
    """Assert config.scheduler is a package (__file__ ends in __init__.py)."""
    import config.scheduler
    assert config.scheduler.__file__.endswith("__init__.py"), \
        f"config.scheduler is not a package: {config.scheduler.__file__}"


def test_gate96_import_run_single_market_rera():
    """Assert from config.scheduler import run_single_market_rera works."""
    from config.scheduler import run_single_market_rera
    assert callable(run_single_market_rera)


def test_gate96_import_run_gcc_daily_scan():
    """Assert from config.scheduler import run_gcc_daily_scan works."""
    from config.scheduler import run_gcc_daily_scan
    assert callable(run_gcc_daily_scan)


def test_gate96_import_run_db_backup():
    """Assert from config.scheduler import run_db_backup works."""
    from config.scheduler import run_db_backup
    assert callable(run_db_backup)


def test_gate96_import_start_scheduler():
    """Assert from config.scheduler import start_scheduler works."""
    from config.scheduler import start_scheduler
    assert callable(start_scheduler)
