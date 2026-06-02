"""Tests for benchmark_rera.py (Sprint 36 — RERA Accuracy Benchmark)"""
import json
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestParseModelResponse:
    def test_valid_json(self):
        """Valid JSON string should be parsed correctly."""
        from scripts.benchmark_rera import parse_model_response
        result = parse_model_response('{"project_name": "Test", "developer": "Brigade"}')
        assert result is not None
        assert result["project_name"] == "Test"

    def test_json_in_text(self):
        """JSON embedded in explanatory text should be extracted."""
        from scripts.benchmark_rera import parse_model_response
        raw = 'Here is the result: {"project_name": "P1", "developer": "Brigade"} End.'
        result = parse_model_response(raw)
        assert result is not None
        assert result["project_name"] == "P1"

    def test_empty_string(self):
        """Empty string should return None."""
        from scripts.benchmark_rera import parse_model_response
        assert parse_model_response("") is None
        assert parse_model_response(None) is None


class TestNormalize:
    def test_lowercase_and_strip(self):
        """Normalize should lowercase and strip whitespace."""
        from scripts.benchmark_rera import normalize
        assert normalize("  Brigade  ") == "brigade"
        assert normalize("BRIGADE ENTERPRISES") == "brigade enterprises"

    def test_none_returns_empty(self):
        """None input should return empty string."""
        from scripts.benchmark_rera import normalize
        assert normalize(None) == ""


class TestCompareRecords:
    def test_exact_match(self):
        """Exact field match should return all matches True."""
        from scripts.benchmark_rera import compare_records
        pred = {"project_name": "Test", "developer": "Brigade", "units": 100,
                "completion_date": "2025-12-31", "rera_id": "RERA/001"}
        truth = {"project_name": "Test", "developer": "Brigade", "units": 100,
                 "completion_date": "2025-12-31", "rera_id": "RERA/001"}
        comp = compare_records(pred, truth)
        assert all(v["match"] for v in comp.values())

    def test_case_insensitive(self):
        """Comparison should be case-insensitive."""
        from scripts.benchmark_rera import compare_records
        pred = {"project_name": "test", "developer": "brigade"}
        truth = {"project_name": "Test", "developer": "Brigade"}
        comp = compare_records(pred, truth)
        for k, v in comp.items():
            if k in ("project_name", "developer"):
                assert v["match"], f"{k} should match case-insensitively"

    def test_field_mismatch(self):
        """Mismatched fields should return match=False."""
        from scripts.benchmark_rera import compare_records
        pred = {"project_name": "Wrong"}
        truth = {"project_name": "Correct"}
        comp = compare_records(pred, truth)
        assert not comp["project_name"]["match"]
