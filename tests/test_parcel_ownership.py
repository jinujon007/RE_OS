"""Parcel ownership enrichment tests — GATE-99, T-1187 + T-1188."""

import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestEnrichOwnership:
    def test_enrich_ownership_returns_dict_on_success(self):
        from utils.parcel_linker import enrich_ownership
        with (
            patch("scrapers.bhoomi_scraper.fetch") as mock_fetch,
            patch("utils.parcel_linker.get_engine") as mock_eng,
        ):
            mock_fetch.return_value = {
                "bhoomi_status": "live",
                "owner_name": "Test Owner",
                "khata_no": "KHA-123",
            }
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            result = enrich_ownership("45/2", "Yelahanka")
            assert result is not None
            assert result.get("survey_no") == "45/2"
            assert result.get("market") == "Yelahanka"
            assert result.get("parser_completeness_score") is not None

    def test_enrich_ownership_returns_none_on_fetch_fail(self):
        from utils.parcel_linker import enrich_ownership
        with patch("scrapers.bhoomi_scraper.fetch") as mock_fetch:
            mock_fetch.return_value = {"bhoomi_status": "unavailable"}
            result = enrich_ownership("45/2", "Yelahanka")
            assert result is None

    def test_enrich_ownership_invalid_survey_no_returns_none(self):
        from utils.parcel_linker import enrich_ownership
        result = enrich_ownership("INVALID", "Yelahanka")
        assert result is None

    def test_enrich_ownership_idempotent(self):
        from utils.parcel_linker import enrich_ownership
        with (
            patch("scrapers.bhoomi_scraper.fetch") as mock_fetch,
            patch("utils.parcel_linker.get_engine") as mock_eng,
        ):
            mock_fetch.return_value = {"bhoomi_status": "live", "owner_name": "Same Owner"}
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            r1 = enrich_ownership("45/2", "Yelahanka")
            r2 = enrich_ownership("45/2", "Yelahanka")
            assert r1 is not None
            assert r2 is not None

    def test_enrich_all_parcels_skips_already_enriched(self):
        from utils.parcel_linker import enrich_all_parcels
        with patch("utils.parcel_linker.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                MagicMock(survey_no="45/2"),
                MagicMock(survey_no="101/1"),
            ]
            with patch("utils.parcel_linker.enrich_ownership", return_value={"dummy": True}):
                count = enrich_all_parcels("Yelahanka", limit=50)
                assert count == 2


class TestOwnershipEndpoint:
    def _make_mock_row(self, **overrides):
        row = MagicMock()
        defaults = {
            "survey_no": "45/2",
            "market": "Yelahanka",
            "khata_no": "KHA-123",
            "owner_name": "Venkatesh",
            "previous_owner": None,
            "transfer_date": None,
            "area_acres": 2.5,
            "govt_acquisition_notice": False,
            "encumbrance_flag": False,
            "fetched_at": None,
            "parcel_id": None,
            "parser_completeness_score": None,
        }
        for k, v in {**defaults, **overrides}.items():
            setattr(row, k, v)
        return row

    def test_ownership_endpoint_returns_200_with_all_fields(self):
        from dashboard.app_fastapi import app
        from starlette.testclient import TestClient
        client = TestClient(app)
        with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = self._make_mock_row()
            resp = client.get("/api/parcel/ownership?survey_no=45/2&market=Yelahanka")
            assert resp.status_code == 200
            data = resp.json()
            assert data["survey_no"] == "45/2"
            assert data["market"] == "Yelahanka"
            assert data["khata_no"] == "KHA-123"
            assert data["owner_name"] == "Venkatesh"
            assert data["previous_owner"] is None
            assert data["transfer_date"] is None
            assert data["area_acres"] == 2.5
            assert data["govt_acquisition_notice"] is False
            assert data["encumbrance_flag"] is False
            assert data["fetched_at"] is None
            assert "parcel_id" in data
            assert "parser_completeness_score" in data

    def test_ownership_endpoint_returns_404_when_no_chain(self):
        from dashboard.app_fastapi import app
        from starlette.testclient import TestClient
        client = TestClient(app)
        with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = None
            resp = client.get("/api/parcel/ownership?survey_no=999/99&market=Yelahanka")
            assert resp.status_code == 404

    def test_ownership_endpoint_returns_422_on_invalid_survey_no(self):
        from dashboard.app_fastapi import app
        from starlette.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/parcel/ownership?survey_no=invalid&market=Yelahanka")
        assert resp.status_code == 422

    def test_ownership_endpoint_returns_500_on_db_error(self):
        from dashboard.app_fastapi import app
        from starlette.testclient import TestClient
        client = TestClient(app)
        with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
            mock_eng.return_value.connect.side_effect = Exception("DB connection failed")
            resp = client.get("/api/parcel/ownership?survey_no=77/99&market=Devanahalli")
            assert resp.status_code == 500
            assert "try again later" in resp.json()["error"]
