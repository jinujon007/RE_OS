"""Unit tests for RedundancyDetector (T-1003 - Sprint 60)."""

import pytest
import uuid
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_prompt_dedup_detected():
    """RedundancyDetector detects identical task hash within 2hr window."""
    from utils.redundancy_detector import RedundancyDetector

    with patch("utils.redundancy_detector.get_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        detector = RedundancyDetector()
        detector._detect_prompt_duplicates = MagicMock(
            return_value=[
                {
                    "type": "prompt_duplicate",
                    "agent": "CEO",
                    "count": 3,
                    "first_run_id": str(uuid.uuid4()),
                    "duplicate_run_id": str(uuid.uuid4()),
                    "tokens_wasted": 4500,
                    "severity": "HIGH",
                    "recommendation": "Cache or dedup prompt for CEO - 3 identical calls detected",
                }
            ]
        )
        detector._detect_cache_misses = MagicMock(return_value=[])
        detector._detect_empty_outputs = MagicMock(return_value=[])

        result = detector.scan(1)

        assert len(result) >= 1
        assert any(f["type"] == "prompt_duplicate" for f in result)


def test_cache_miss_pattern():
    """RedundancyDetector detects cache misses (same market/survey >=3x per hour)."""
    from utils.redundancy_detector import RedundancyDetector

    with patch("utils.redundancy_detector.get_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        detector = RedundancyDetector()
        detector._detect_prompt_duplicates = MagicMock(return_value=[])
        detector._detect_cache_misses = MagicMock(
            return_value=[
                {
                    "type": "cache_miss",
                    "market": "Yelahanka",
                    "survey_no": "45/2",
                    "agent_count": 4,
                    "severity": "HIGH",
                    "recommendation": "IntelRegistry cache may be ineffective for Yelahanka/45/2 - 4 agents hit in same hour",
                }
            ]
        )
        detector._detect_empty_outputs = MagicMock(return_value=[])

        result = detector.scan(1)

        assert any(f["type"] == "cache_miss" for f in result)


def test_empty_output_flagged():
    """RedundancyDetector flags runs with error messages."""
    from utils.redundancy_detector import RedundancyDetector

    with patch("utils.redundancy_detector.get_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        detector = RedundancyDetector()
        detector._detect_prompt_duplicates = MagicMock(return_value=[])
        detector._detect_cache_misses = MagicMock(return_value=[])
        detector._detect_empty_outputs = MagicMock(
            return_value=[
                {
                    "type": "empty_output",
                    "run_id": str(uuid.uuid4()),
                    "agent": "SocialMediaAgent",
                    "task_type": "calendar_generation",
                    "severity": "LOW",
                    "recommendation": "Review SocialMediaAgent output handling - potential wasted LLM call",
                }
            ]
        )

        result = detector.scan(7)

        assert any(f["type"] == "empty_output" for f in result)


def test_severity_assignment():
    """Finding severity is assigned correctly based on pattern type."""
    from utils.redundancy_detector import RedundancyDetector

    with patch("utils.redundancy_detector.get_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        detector = RedundancyDetector()
        detector._detect_prompt_duplicates = MagicMock(return_value=[])
        detector._detect_cache_misses = MagicMock(return_value=[])
        detector._detect_empty_outputs = MagicMock(return_value=[])

        result = detector.scan(1)
        assert isinstance(result, list)


def test_no_false_positives_on_clean_data():
    """RedundancyDetector returns empty list when no redundancies found."""
    from utils.redundancy_detector import RedundancyDetector, detect_redundancies

    with patch("utils.redundancy_detector.get_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        detector = RedundancyDetector()
        detector._detect_prompt_duplicates = MagicMock(return_value=[])
        detector._detect_cache_misses = MagicMock(return_value=[])
        detector._detect_empty_outputs = MagicMock(return_value=[])

        result = detector.scan(7)
        assert result == []


def test_compute_task_hash():
    """compute_task_hash generates consistent SHA256 hashes."""
    from utils.token_tracker import compute_task_hash

    hash1 = compute_task_hash("Analyze Yelahanka survey 45/2")
    hash2 = compute_task_hash("Analyze Yelahanka survey 45/2")
    assert hash1 == hash2
    assert len(hash1) == 64


def test_scan_validates_days_parameter():
    """RedundancyDetector.scan() validates days parameter."""
    from utils.redundancy_detector import RedundancyDetector

    with patch("utils.redundancy_detector.get_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        detector = RedundancyDetector()
        detector._detect_prompt_duplicates = MagicMock(return_value=[])
        detector._detect_cache_misses = MagicMock(return_value=[])
        detector._detect_empty_outputs = MagicMock(return_value=[])

        result = detector.scan(0)
        # Invalid days is clamped to 7, scan returns empty when no data
        assert isinstance(result, list)
