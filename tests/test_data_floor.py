"""T-1290 — Data floor auto-update."""
import time
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def test_get_data_floor_returns_int():
    from config.settings import get_data_floor, _data_floor_cache
    _data_floor_cache.clear()
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__.return_value = 100
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        floor = get_data_floor("Yelahanka")
        assert isinstance(floor, int)


def test_get_data_floor_uses_live_count_when_available():
    from config.settings import get_data_floor, _data_floor_cache
    _data_floor_cache.clear()
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__.return_value = 500
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        floor = get_data_floor("Yelahanka")
        assert floor == 250


def test_get_data_floor_falls_back_to_hardcoded():
    from config.settings import get_data_floor, _data_floor_cache
    _data_floor_cache.clear()
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__.return_value = 50
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        floor = get_data_floor("Yelahanka")
        assert floor == 50


def test_get_data_floor_db_error_falls_back():
    from config.settings import get_data_floor, _data_floor_cache
    _data_floor_cache.clear()
    with patch("utils.db.get_engine", side_effect=Exception("DB down")):
        floor = get_data_floor("Yelahanka")
        assert floor == 50, "Should fall back to hardcoded 50 on DB error"


def test_get_data_floor_cache_ttl_respected():
    from config.settings import get_data_floor, _data_floor_cache
    _data_floor_cache.clear()
    cache_key = "CacheTest"
    _data_floor_cache[cache_key] = (99, time.time())
    with patch("utils.db.get_engine") as mock_eng:
        floor = get_data_floor(cache_key)
        assert floor == 99
        mock_eng.assert_not_called()
