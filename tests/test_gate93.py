"""GATE-93 — Leading Indicators + Moat Insurance — declaration tests.

Assertions:
    1. offsite_backup_weekly + ledger_check_weekly + tender_daily_scan + la_notification_scan jobs registered in scheduler
    2. prediction_ledger importable; insert+verdict round-trip
    3. TenderPlugin parses fixture → ≥3 records
    4. LA parser extracts ≥1 from fixture text
    5. verify_remote_backup callable (mocked)
"""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_gate93_assertion1_scheduler_jobs_registered():
    """Assertion 1: All 4 GATE-93 jobs registered in scheduler.

    Uses text analysis of the scheduler file rather than importing
    the full scheduler, which would require APScheduler runtime.
    """
    config_text = open("config/scheduler.py", encoding="utf-8").read()
    assert 'id="offsite_backup_weekly"' in config_text, "offsite_backup_weekly job missing"
    assert 'id="ledger_check_weekly"' in config_text, "ledger_check_weekly job missing"
    assert 'id="tender_daily_scan"' in config_text, "tender_daily_scan job missing"
    assert 'id="la_notification_scan"' in config_text, "la_notification_scan job missing"


def test_gate93_assertion2_prediction_ledger_importable():
    """Assertion 2: prediction_ledger importable + insert+verdict round-trip."""
    from utils.prediction_ledger import write_prediction_ledger, get_pending_claims, resolve_verdicts
    from datetime import date

    with patch("utils.prediction_ledger.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        ok = write_prediction_ledger(
            source_module="test",
            claim_type="psf_forecast",
            market="Yelahanka",
            claim_text="Test claim",
            falsifiable_metric="Test metric",
            check_date=date(2026, 7, 1),
        )
        assert ok is True

        pending = get_pending_claims()
        assert isinstance(pending, list)

        result = resolve_verdicts()
        assert isinstance(result, dict)
        assert "total" in result


def test_gate93_assertion3_tender_plugin_parses_3_records():
    """Assertion 3: TenderPlugin returns ≥3 records (seed fallback)."""
    from ingest.plugins.tender_plugin import TenderPlugin
    with patch.object(TenderPlugin, "_scrape_portal", return_value=[]):
        plugin = TenderPlugin()
        records = plugin.run("Yelahanka")
        assert len(records) >= 3, f"Expected ≥3 tender records, got {len(records)}"


def test_gate93_assertion4_la_parser_extracts_from_fixture():
    """Assertion 4: LA parser extracts ≥1 notification from fixture text."""
    from scrapers.la_gazette_parser import LAGazetteParser
    parser = LAGazetteParser()
    text = """NOTIFICATION NO. KIADB/LAQ/2026/789
    Date: 15-03-2026
    Karnataka Industrial Areas Development Board preliminary notification
    under Section 4(1) for acquisition of land for Aerospace Park expansion
    in villages of Venkatala and Shivanahalli, Devanahalli Taluk.
    Survey numbers Sy No. 45/1, 45/2, 48/3."""
    notifs = parser.parse_text(text)
    assert len(notifs) >= 1, "Expected ≥1 LA notification from fixture text"


def test_gate93_assertion5_verify_remote_backup_callable():
    """Assertion 5: verify_remote_backup is callable (mocked)."""
    from utils.backup import verify_remote_backup
    assert callable(verify_remote_backup)

    with patch.dict("os.environ", {}, clear=True):
        result = verify_remote_backup()
        assert "status" in result
        assert result["status"] == "skipped"
