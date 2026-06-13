"""Tests for prediction_ledger table + ledger utility (GATE-93, T-1147/T-1148)."""
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_prediction_ledger_migration_syntax():
    """Verify migration 0057 is syntactically valid."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "migration_0057",
        "alembic/versions/0057_prediction_ledger.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
    assert mod.revision == "0057_prediction_ledger"
    assert mod.down_revision == "0056_assembly_signals"


def test_write_prediction_ledger():
    """write_prediction_ledger inserts a row with correct fields."""
    from utils.prediction_ledger import write_prediction_ledger
    with patch("utils.prediction_ledger.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.rowcount = 1

        result = write_prediction_ledger(
            source_module="test_module",
            claim_type="psf_forecast",
            market="Yelahanka",
            claim_text="PSF to reach 12000 by June 2026",
            falsifiable_metric="registered_transactions.psf >= 12000",
            predicted_value=12000,
            check_date=date(2026, 6, 30),
            confidence=0.8,
        )
        assert result is True
        assert mock_conn.execute.called
        call_kwargs = mock_conn.execute.call_args[0][1]
        assert call_kwargs["source_module"] == "test_module"
        assert call_kwargs["market"] == "Yelahanka"


def test_write_prediction_ledger_failure_does_not_raise():
    """write_prediction_ledger returns False on DB error instead of raising."""
    from utils.prediction_ledger import write_prediction_ledger
    with patch("utils.db.get_engine", side_effect=RuntimeError("DB down")):
        result = write_prediction_ledger(
            source_module="test",
            claim_type="opportunity_score",
            market="Devanahalli",
            claim_text="Score > 0.7",
            falsifiable_metric="opportunity_scores.score > 0.7",
            check_date=date(2026, 7, 1),
        )
        assert result is False


def test_ledger_check_weekly_function_exists():
    """config.scheduler has callable run_ledger_check_weekly."""
    import config.scheduler
    assert callable(config.scheduler.run_ledger_check_weekly)


def test_get_pending_claims_returns_list():
    """get_pending_claims returns list of dicts with expected keys."""
    from utils.prediction_ledger import get_pending_claims
    with patch("utils.prediction_ledger.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_row = MagicMock()
        mock_row._mapping = {
            "id": "uuid-1",
            "date_made": date(2026, 6, 1),
            "source_module": "psf_forecaster",
            "claim_type": "psf_forecast",
            "market": "Yelahanka",
            "claim_text": "test",
            "falsifiable_metric": "test",
            "predicted_value": 12000,
            "check_date": date(2026, 7, 1),
            "confidence": 0.8,
        }
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]

        claims = get_pending_claims()
        assert len(claims) == 1
        assert claims[0]["source_module"] == "psf_forecaster"
        assert claims[0]["market"] == "Yelahanka"


def test_psf_forecaster_writes_to_prediction_ledger():
    """PSFForecaster.forecast() writes prediction_ledger row on successful forecast."""
    from utils.psf_forecaster import PSFForecaster
    with (
        patch("utils.psf_forecaster.PSFForecaster._load_monthly_series") as mock_load,
        patch("utils.prediction_ledger.write_prediction_ledger") as mock_write,
    ):
        mock_load.return_value = [
            (datetime(2025, 1, 1), 8000),
            (datetime(2025, 2, 1), 8200),
            (datetime(2025, 3, 1), 8300),
            (datetime(2025, 4, 1), 8500),
            (datetime(2025, 5, 1), 8600),
        ]
        result = PSFForecaster().forecast("Yelahanka")
        assert result.status == "ok"
        assert mock_write.called
        call_kwargs = mock_write.call_args[1]
        assert call_kwargs["source_module"] == "psf_forecaster"
        assert call_kwargs["claim_type"] == "psf_forecast"


def test_assembly_detector_writes_to_prediction_ledger():
    """detect_assemblies writes prediction_ledger rows for each signal."""
    import datetime
    from utils.assembly_detector import detect_assemblies
    mock_rows = [
        MagicMock(id="1", buyer_name_raw="BRIGADE GROUP", village="Venkatala",
                  survey_no="45/1", reg_date=datetime.date(2026, 1, 15),
                  extent_sqft=10000, consideration_inr=5000000),
        MagicMock(id="2", buyer_name_raw="BRIGADE ENTERPRISES", village="Venkatala",
                  survey_no="45/3", reg_date=datetime.date(2026, 3, 10),
                  extent_sqft=15000, consideration_inr=8000000),
    ]
    with (
        patch("utils.assembly_detector.get_engine") as mock_eng,
        patch("utils.prediction_ledger.write_prediction_ledger") as mock_write,
    ):
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        signals = detect_assemblies()
        if signals:
            assert mock_write.called
            call_kwargs = mock_write.call_args[1]
            assert call_kwargs["source_module"] == "assembly_detector"
            assert call_kwargs["claim_type"] == "assembly_alert"


def test_resolve_verdicts_checks_psf_market():
    """resolve_verdicts queries registered_transactions for PSF forecasts."""
    from utils.prediction_ledger import resolve_verdicts
    mock_row = MagicMock()
    mock_row._mapping = {
        "id": "uuid-1",
        "date_made": datetime(2026, 6, 1).date(),
        "source_module": "psf_forecaster",
        "claim_type": "psf_forecast",
        "market": "Yelahanka",
        "claim_text": "test",
        "falsifiable_metric": "test",
        "predicted_value": 12000,
        "check_date": datetime(2026, 6, 13).date(),
        "confidence": 0.8,
    }
    with (
        patch("utils.prediction_ledger.get_engine") as mock_eng,
    ):
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        mock_conn.execute.return_value.fetchone.return_value = None  # no PSF data → unverifiable

        result = resolve_verdicts()
        assert result["total"] == 1
        assert result["unverifiable"] == 1


def test_market_name_from_id_resolves():
    """_market_name_from_id resolves market name from ID."""
    from intelligence.opportunity_engine import OpportunityEngine
    engine = OpportunityEngine()
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = ("Yelahanka",)
        name = engine._market_name_from_id("some-uuid")
        assert name == "Yelahanka"
