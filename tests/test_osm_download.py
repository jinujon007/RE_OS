"""Tests for utils/osm_download.py — T-715 OSM street network downloader."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _mock_osmnx():
    """Create a mock osmnx module that can be injected into sys.modules."""
    mock = MagicMock()
    mock.graph_from_place.return_value = mock
    mock.number_of_nodes.return_value = 100
    mock.number_of_edges.return_value = 200
    return mock


class TestGetGraphmlPath:
    def test_simple_market_name(self):
        from utils.osm_download import get_graphml_path
        p = get_graphml_path("Yelahanka")
        assert p.name == "yelahanka.graphml"

    def test_market_name_with_spaces(self):
        from utils.osm_download import get_graphml_path
        p = get_graphml_path("Doddaballapur Road")
        assert p.name == "doddaballapur_road.graphml"

    def test_uses_env_var_dir(self):
        with patch("utils.osm_download._OSM_DATA_DIR", Path("/tmp/test_osm")):
            from utils.osm_download import get_graphml_path
            p = get_graphml_path("Hebbal")
            assert "test_osm" in str(p)


class TestDownloadMarket:
    def test_empty_market_returns_false(self):
        from utils.osm_download import download_market
        assert download_market("") is False
        assert download_market("   ") is False

    def test_unknown_market_returns_false(self):
        from utils.osm_download import download_market
        assert download_market("Nonexistent") is False

    def test_cache_hit_returns_true(self, tmp_path):
        cache_file = tmp_path / "yelahanka.graphml"
        cache_file.touch()
        mock_ox = _mock_osmnx()
        with patch("utils.osm_download._OSM_DATA_DIR", tmp_path), \
             patch.dict("sys.modules", {"osmnx": mock_ox}):
            from utils.osm_download import download_market
            assert download_market("Yelahanka") is True

    def test_force_redownloads(self, tmp_path):
        cache_file = tmp_path / "yelahanka.graphml"
        cache_file.write_text("old")
        mock_ox = _mock_osmnx()
        with patch("utils.osm_download._OSM_DATA_DIR", tmp_path), \
             patch.dict("sys.modules", {"osmnx": mock_ox}):
            from utils.osm_download import download_market
            result = download_market("Yelahanka", force=True)
            assert result is True
            mock_ox.save_graphml.assert_called_once()

    def test_download_failure_returns_false(self, tmp_path):
        mock_ox = _mock_osmnx()
        mock_ox.graph_from_place.side_effect = Exception("OSM API down")
        with patch("utils.osm_download._OSM_DATA_DIR", tmp_path), \
             patch.dict("sys.modules", {"osmnx": mock_ox}):
            from utils.osm_download import download_market
            assert download_market("Yelahanka") is False


class TestDownloadAll:
    def test_returns_dict_with_all_markets(self):
        from utils.osm_download import download_all
        with patch("utils.osm_download.download_market", return_value=True):
            results = download_all()
            assert isinstance(results, dict)
            assert "Yelahanka" in results
            assert "Devanahalli" in results
            assert "Hebbal" in results
            assert all(v is True for v in results.values())

    def test_partial_failures_reflected(self):
        from utils.osm_download import download_all
        def _side_effect(market, force=False):
            return market == "Yelahanka"
        with patch("utils.osm_download.download_market", side_effect=_side_effect):
            results = download_all()
            assert results["Yelahanka"] is True
            assert results["Devanahalli"] is False
            assert results["Hebbal"] is False
