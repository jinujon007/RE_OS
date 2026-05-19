"""
Unit tests for config/checkpointer.py

Uses a tmp_path fixture so tests never touch the real outputs/ directory.
"""
import json
import os
from datetime import date

import pytest

from config.checkpointer import Checkpointer


@pytest.fixture
def cp(tmp_path):
    return Checkpointer(base_dir=str(tmp_path))


def test_save_returns_path(cp, tmp_path):
    path = cp.save("Yelahanka", "rera_scraped", [{"id": 1}])
    assert path.endswith(".json")
    assert os.path.exists(path)


def test_save_load_roundtrip(cp):
    data = [{"rera_number": "PRM/KA/001", "project_name": "Test"}]
    cp.save("Yelahanka", "rera_scraped", data)
    loaded = cp.load("Yelahanka", "rera_scraped")
    assert loaded == data


def test_load_returns_none_when_not_found(cp):
    result = cp.load("Hebbal", "rera_scraped")
    assert result is None


def test_exists_true_after_save(cp):
    assert not cp.exists("Devanahalli", "listings")
    cp.save("Devanahalli", "listings", {"count": 5})
    assert cp.exists("Devanahalli", "listings")


def test_exists_false_before_save(cp):
    assert cp.exists("Yelahanka", "kaveri") is False


def test_save_overwrites_existing(cp):
    cp.save("Yelahanka", "rera_scraped", [{"v": 1}])
    cp.save("Yelahanka", "rera_scraped", [{"v": 2}])
    loaded = cp.load("Yelahanka", "rera_scraped")
    assert loaded == [{"v": 2}]


def test_load_returns_none_for_corrupt_json(cp):
    path = cp.path("Yelahanka", "corrupt_task")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{ this is not valid json")
    result = cp.load("Yelahanka", "corrupt_task")
    assert result is None


def test_path_contains_today_date(cp):
    path = cp.path("Hebbal", "rera_scraped")
    today = date.today().isoformat()
    assert today in path


def test_market_slug_lowercases_and_replaces_spaces(cp):
    cp.save("North Bengaluru", "rera_scraped", [])
    assert cp.exists("North Bengaluru", "rera_scraped")
    path = cp.path("North Bengaluru", "rera_scraped")
    assert "north_bengaluru" in path
