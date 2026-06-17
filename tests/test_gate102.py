"""GATE-102 declaration — Kill Criteria Checkpoint.

4 assertions:
1. KillCriteriaAuditor importable from utils.kill_criteria
2. check_deed_throughput(MagicMock()) returns dict with status key
3. check_corridor_accuracy returns dict with status key (mocked CorridorScorerV2)
4. check_decision_journal returns dict with entry_count key (real journal file)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_kill_criteria_importable():
    from utils.kill_criteria import KillCriteriaAuditor

    assert KillCriteriaAuditor is not None


def test_deed_throughput_returns_dict_with_status():
    from utils.kill_criteria import KillCriteriaAuditor

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
    auditor = KillCriteriaAuditor(engine=mock_engine)
    result = auditor.check_deed_throughput(engine=mock_engine)
    assert "status" in result


def test_corridor_accuracy_returns_dict():
    from utils.kill_criteria import KillCriteriaAuditor

    mock_engine = MagicMock()
    with patch("utils.kill_criteria.CorridorScorerV2") as MockScorer:
        MockScorer.return_value.backtest.return_value = {"verdict": "INSUFFICIENT_DATA"}
        auditor = KillCriteriaAuditor(engine=mock_engine)
        result = auditor.check_corridor_accuracy(engine=mock_engine)
    assert "status" in result
    assert "verdict" in result


def test_decision_journal_returns_entry_count():
    from utils.kill_criteria import KillCriteriaAuditor

    journal_path = Path("docs/decision_journal.md")
    assert journal_path.exists(), "decision_journal.md must exist"

    auditor = KillCriteriaAuditor(engine=MagicMock())
    result = auditor.check_decision_journal(journal_path=str(journal_path))
    assert "entry_count" in result
    assert isinstance(result["entry_count"], int)
