"""T-1289 — Confidence decay live validation job."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def test_confidence_decay_check_registered():
    content = Path("config/scheduler/maintenance_jobs.py").read_text()
    assert "def run_confidence_decay_check" in content


def test_confidence_decay_check_alerts_on_zero_updates():
    content = Path("config/scheduler/maintenance_jobs.py").read_text()
    assert "send_ops_alert" in content
    assert "0 memory records updated this week" in content
    assert "CONFIDENCE_DECAY_STALLED" in content


def test_confidence_decay_check_silent_on_healthy():
    content = Path("config/scheduler/maintenance_jobs.py").read_text()
    assert "records decayed this week" in content
