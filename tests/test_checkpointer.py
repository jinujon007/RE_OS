"""
Tests for config/checkpointer.py

Covers: save, load, exists, path, cleanup_old, _market_slug, atomic write,
directory auto-creation, overwrite, corrupt file, today-dated paths.

All I/O is redirected to pytest's tmp_path — no writes to the real outputs/ dir.
"""

import json
import os
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from config.checkpointer import Checkpointer


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def cp(tmp_path):
    """Checkpointer rooted at a temp directory."""
    return Checkpointer(base_dir=str(tmp_path))


# ── _market_slug ───────────────────────────────────────────────────────────────


def test_market_slug_lowercase(cp):
    assert cp._market_slug("Yelahanka") == "yelahanka"


def test_market_slug_spaces_replaced(cp):
    assert cp._market_slug("North Bengaluru") == "north_bengaluru"


def test_market_slug_already_lower(cp):
    assert cp._market_slug("devanahalli") == "devanahalli"


# ── _path ──────────────────────────────────────────────────────────────────────


def test_path_format(cp, tmp_path):
    today = date.today().isoformat()
    expected = os.path.join(
        str(tmp_path), "yelahanka", "checkpoints", f"rera_scraped_{today}.json"
    )
    assert cp._path("Yelahanka", "rera_scraped") == expected


def test_path_normalises_market(cp, tmp_path):
    p = cp._path("North Bengaluru", "listings")
    assert "north_bengaluru" in p


# ── save + load ────────────────────────────────────────────────────────────────


def test_save_creates_file(cp):
    cp.save("Yelahanka", "rera_scraped", [{"rera": "KA/01/1"}])
    assert cp.exists("Yelahanka", "rera_scraped")


def test_save_returns_path(cp):
    result = cp.save("Yelahanka", "rera_scraped", [])
    assert result.endswith(".json")
    assert "yelahanka" in result


def test_save_and_load_roundtrip(cp):
    data = [{"rera_number": "KA/01/1", "psf": 5500}]
    cp.save("Yelahanka", "rera_scraped", data)
    loaded = cp.load("Yelahanka", "rera_scraped")
    assert loaded == data


def test_save_creates_parent_dirs(cp, tmp_path):
    # Directory should not exist yet
    slug_dir = tmp_path / "hebbal" / "checkpoints"
    assert not slug_dir.exists()
    cp.save("Hebbal", "listings", {"key": "val"})
    assert slug_dir.exists()


def test_save_overwrites_existing(cp):
    cp.save("Yelahanka", "rera_scraped", [{"v": 1}])
    cp.save("Yelahanka", "rera_scraped", [{"v": 2}])
    loaded = cp.load("Yelahanka", "rera_scraped")
    assert loaded == [{"v": 2}]


def test_save_no_tmp_file_left(cp, tmp_path):
    """Atomic write: no .tmp file should remain after save."""
    cp.save("Yelahanka", "rera_scraped", [1, 2, 3])
    cp_dir = tmp_path / "yelahanka" / "checkpoints"
    tmp_files = [f for f in os.listdir(cp_dir) if f.endswith(".tmp")]
    assert tmp_files == []


def test_save_dict_data(cp):
    data = {"market": "Yelahanka", "count": 3}
    cp.save("Yelahanka", "market_brief", data)
    loaded = cp.load("Yelahanka", "market_brief")
    assert loaded == data


# ── load edge cases ────────────────────────────────────────────────────────────


def test_load_missing_returns_none(cp):
    result = cp.load("Yelahanka", "nonexistent_task")
    assert result is None


def test_load_corrupt_file_returns_none(cp, tmp_path):
    """A truncated / malformed JSON file should return None, not raise."""
    cp_dir = tmp_path / "yelahanka" / "checkpoints"
    cp_dir.mkdir(parents=True)
    today = date.today().isoformat()
    bad_file = cp_dir / f"rera_scraped_{today}.json"
    bad_file.write_text("{{{{not valid json", encoding="utf-8")
    result = cp.load("Yelahanka", "rera_scraped")
    assert result is None


# ── exists ─────────────────────────────────────────────────────────────────────


def test_exists_false_before_save(cp):
    assert cp.exists("Yelahanka", "rera_scraped") is False


def test_exists_true_after_save(cp):
    cp.save("Yelahanka", "rera_scraped", [])
    assert cp.exists("Yelahanka", "rera_scraped") is True


# ── path (public alias) ────────────────────────────────────────────────────────


def test_path_public_matches_internal(cp):
    assert cp.path("Yelahanka", "rera_scraped") == cp._path("Yelahanka", "rera_scraped")


# ── cleanup_old ────────────────────────────────────────────────────────────────


def test_cleanup_old_removes_stale_files(cp, tmp_path):
    cp_dir = tmp_path / "yelahanka" / "checkpoints"
    cp_dir.mkdir(parents=True)

    old_date = (date.today() - timedelta(days=10)).isoformat()
    old_file = cp_dir / f"rera_scraped_{old_date}.json"
    old_file.write_text(json.dumps([]), encoding="utf-8")

    removed = cp.cleanup_old("Yelahanka", keep_days=7)
    assert removed == 1
    assert not old_file.exists()


def test_cleanup_old_keeps_recent_files(cp, tmp_path):
    cp_dir = tmp_path / "yelahanka" / "checkpoints"
    cp_dir.mkdir(parents=True)

    recent_date = (date.today() - timedelta(days=3)).isoformat()
    recent_file = cp_dir / f"rera_scraped_{recent_date}.json"
    recent_file.write_text(json.dumps([]), encoding="utf-8")

    removed = cp.cleanup_old("Yelahanka", keep_days=7)
    assert removed == 0
    assert recent_file.exists()


def test_cleanup_old_missing_dir_returns_zero(cp):
    """cleanup_old must not raise when the checkpoint dir doesn't exist."""
    removed = cp.cleanup_old("NonExistentMarket", keep_days=7)
    assert removed == 0


def test_cleanup_old_skips_non_json_files(cp, tmp_path):
    cp_dir = tmp_path / "yelahanka" / "checkpoints"
    cp_dir.mkdir(parents=True)

    old_date = (date.today() - timedelta(days=10)).isoformat()
    txt_file = cp_dir / f"notes_{old_date}.txt"
    txt_file.write_text("ignore me", encoding="utf-8")

    removed = cp.cleanup_old("Yelahanka", keep_days=7)
    assert removed == 0
    assert txt_file.exists()


def test_cleanup_old_ignores_malformed_filenames(cp, tmp_path):
    """Files without a valid YYYY-MM-DD segment should be left untouched."""
    cp_dir = tmp_path / "yelahanka" / "checkpoints"
    cp_dir.mkdir(parents=True)

    bad_file = cp_dir / "rera_scraped_no_date.json"
    bad_file.write_text(json.dumps([]), encoding="utf-8")

    removed = cp.cleanup_old("Yelahanka", keep_days=7)
    assert removed == 0
    assert bad_file.exists()
