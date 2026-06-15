"""GATE-59 declaration: PSF Forecaster guard, deal alerts, cache TTL."""

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_forecaster_skipped_for_insufficient_data():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            (__import__("datetime").datetime(2025, 1, 1), 6000.0),
        ]
        result = PSFForecaster().forecast("Yelahanka")
    assert result.status == "insufficient_data"
    assert result.data_points == 1


def test_deal_pipeline_discord_fires_for_loi():
    import os

    os.environ.setdefault("REDIS_URL", "memory://")
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    def _fake_row(values):
        m = MagicMock()
        m.__getitem__.side_effect = lambda i: values[i]
        return m

    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "test-key"}):
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.side_effect = [
                ["m-uuid-1"],
                _fake_row(
                    ["d-uuid", "45/2", "loi", 0.82, None, None, None, None, None, None]
                ),
            ]
            with patch("utils.discord_notifier.send") as mock_send:
                client.post(
                    "/api/deals",
                    json={"survey_no": "45/2", "market": "Devanahalli", "stage": "loi"},
                    headers={"X-API-Key": "test-key"},
                )
    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == "bd_opportunities"


def test_cache_ttl_partial_is_shorter_than_full():
    from intelligence.registry import _LRUCache, _PARTIAL_TTL, _POSITIVE_TTL
    from intelligence.registry import IntelPackage

    cache = _LRUCache()
    with patch("intelligence.registry.time.time", return_value=1000.0):
        cache.set(
            "a",
            IntelPackage(
                survey_no="1", market="M", collected_at="", all_modules_success=False
            ),
        )
        cache.set(
            "b",
            IntelPackage(
                survey_no="2", market="M", collected_at="", all_modules_success=True
            ),
        )

    exp_a, _ = cache._store["a"]
    exp_b, _ = cache._store["b"]
    assert exp_a == pytest.approx(1000.0 + _PARTIAL_TTL)
    assert exp_b == pytest.approx(1000.0 + _POSITIVE_TTL)
    assert exp_a < exp_b
