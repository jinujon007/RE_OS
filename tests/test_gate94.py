"""GATE-94 — Demand Truth + Calibration

4 assertions:
(1) gcc_hiring_snapshots table model (via import + migration check)
(2) GCCPlugin prefers snapshots: _get_snapshot_employers method exists
(3) dc_conversions importable + parser fixture round-trip
(4) [UNCALIBRATED] label present in DemandSignals.__str__ pre-calibration
"""

import pytest

pytestmark = pytest.mark.unit


def test_gcc_hiring_snapshots_migration_exists():
    """Assertion 1: gcc_hiring_snapshots migration file exists and table is referenced."""
    from pathlib import Path

    migration_path = Path("alembic/versions/0059_gcc_hiring_snapshots.py")
    assert migration_path.exists(), "Migration 0059 for gcc_hiring_snapshots not found"
    content = migration_path.read_text()
    assert "gcc_hiring_snapshots" in content
    assert "gcc_events" in content  # adds data_source column


def test_gcc_plugin_has_snapshot_methods():
    """Assertion 2: GCCPlugin has _get_snapshot_employers and _scan_hiring_snapshots methods."""
    from ingest.plugins.gcc_plugin import GCCPlugin

    plugin = GCCPlugin.__new__(GCCPlugin)
    assert hasattr(plugin, "_get_snapshot_employers"), (
        "GCCPlugin missing _get_snapshot_employers"
    )
    assert hasattr(plugin, "_scan_hiring_snapshots"), (
        "GCCPlugin missing _scan_hiring_snapshots"
    )
    # seed events get data_source='seed' when snapshot employer is active
    import inspect

    src = inspect.getsource(plugin.run)
    assert "data_source" in src, "GCCPlugin.run must set data_source for demotion"
    assert "snapshot_employers" in src, (
        "GCCPlugin.run must reference snapshot employers"
    )


def test_dc_conversions_importable_and_parser_works():
    """Assertion 3: dc_conversions module importable + parser round-trip."""
    from scrapers.dc_conversion_scraper import (
        _parse_dc_html,
        run_scan,
        market_for_village,
    )

    html = """
    <table>
        <tr><td>DC/001</td><td>Venkatala</td><td>45/2</td><td>1.5</td><td>Agri</td><td>Residential</td><td>John</td><td>Approved</td><td>01-06-2024</td></tr>
    </table>
    """
    records = _parse_dc_html(html)
    assert len(records) == 1
    assert records[0]["application_no"] == "DC/001"
    assert records[0]["village"] == "Venkatala"
    assert market_for_village("Venkatala") == "Yelahanka"


def test_uncallibrated_label_present_pre_calibration():
    """Assertion 4: DemandSignals carries [UNCALIBRATED] label before calibration."""
    from intelligence.demand_intel import DemandSignals

    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-13")
    output = str(ds)
    assert "UNCALIBRATED" in output, (
        f"[UNCALIBRATED] label missing from str(): {output}"
    )
    assert ds.calibration_status == "UNCALIBRATED"
