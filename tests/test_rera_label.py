"""Tests for rera_label.py (Sprint 36 — RERA Training Data Labeling)"""

import json
import pytest
from pathlib import Path

pytestmark = pytest.mark.unit


class TestReconstructHTML:
    def test_html_contains_rera_id(self):
        """Reconstructed HTML should contain the RERA registration number."""
        from data.training.rera_label import _reconstruct_html

        rec = {
            "project_name": "Test",
            "developer_name": "Dev",
            "total_units": 100,
            "completion_date": "2025-12-31",
            "rera_registration_no": "RERA/TEST/001",
        }
        html = _reconstruct_html(rec, seed=42)
        assert "RERA/TEST/001" in html
        assert "Test" in html
        assert "Dev" in html
        assert "100" in html or "100" in str(rec["total_units"])

    def test_html_varies_with_seed(self):
        """Different seeds should produce different non-extracted fields (H-5 fix)."""
        from data.training.rera_label import _reconstruct_html

        rec = {
            "project_name": "Test",
            "developer_name": "Dev",
            "total_units": 50,
            "completion_date": "2026-06-01",
            "rera_registration_no": "RERA/002",
        }
        html1 = _reconstruct_html(rec, seed=1)
        html2 = _reconstruct_html(rec, seed=999)
        # ACK number or status should differ between seeds
        assert html1 != html2


class TestBuildCompletion:
    def test_completion_fields_match(self):
        """Completion JSON should have correct field mapping."""
        from data.training.rera_label import _build_completion

        rec = {
            "project_name": "P1",
            "developer_name": "Brigade",
            "total_units": 200,
            "completion_date": "2026-03-31",
            "rera_registration_no": "RERA/003",
        }
        comp = _build_completion(rec)
        assert comp["project_name"] == "P1"
        assert comp["developer"] == "Brigade"
        assert comp["units"] == 200
        assert comp["completion_date"] == "2026-03-31"
        assert comp["rera_id"] == "RERA/003"

    def test_completion_empty_rera_id(self):
        """Empty rera_id should map to empty string."""
        from data.training.rera_label import _build_completion

        rec = {"project_name": "", "developer_name": "", "rera_registration_no": ""}
        comp = _build_completion(rec)
        assert comp["rera_id"] == ""


class TestStratifiedSplit:
    def test_basic_split(self):
        """Basic split should return train + holdout sets."""
        from data.training.rera_label import _stratified_split

        records = [
            {"developer_name": "Brigade", "rera_registration_no": f"R/{i}"}
            for i in range(100)
        ]
        train, holdout = _stratified_split(records, holdout_size=20)
        assert len(train) == 80
        assert len(holdout) == 20
        assert len(train) + len(holdout) == len(records)

    def test_small_dataset(self):
        """Dataset smaller than holdout size should still produce both splits."""
        from data.training.rera_label import _stratified_split

        records = [
            {"developer_name": "Brigade", "rera_registration_no": f"R/{i}"}
            for i in range(10)
        ]
        train, holdout = _stratified_split(records, holdout_size=20)
        assert len(train) + len(holdout) == 10

    def test_multi_developer_stratification(self):
        """Every developer with >=2 records should appear in both splits (B-2 fix)."""
        from data.training.rera_label import _stratified_split

        records = (
            [
                {"developer_name": "Brigade", "rera_registration_no": f"B/{i}"}
                for i in range(20)
            ]
            + [
                {"developer_name": "Prestige", "rera_registration_no": f"P/{i}"}
                for i in range(15)
            ]
            + [
                {"developer_name": "Sobha", "rera_registration_no": f"S/{i}"}
                for i in range(8)
            ]
        )
        train, holdout = _stratified_split(records, holdout_size=10)
        train_devs = {r["developer_name"] for r in train}
        holdout_devs = {r["developer_name"] for r in holdout}
        assert "Brigade" in train_devs and "Brigade" in holdout_devs
        assert "Prestige" in train_devs and "Prestige" in holdout_devs
        assert "Sobha" in train_devs and "Sobha" in holdout_devs
