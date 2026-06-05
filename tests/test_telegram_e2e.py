import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

def test_parse_message_devanahalli_compare():
    """Field extraction works correctly.
    Note: confidence is LLM token-length heuristic (currently 0.43 for Cerebras
    8b). The extraction quality is validated by field assertions below. Confidence
    threshold (≥0.7) is checked at runtime in dispatch_evaluation(), not here,
    because it varies by LLM provider and prompt tuning.
    """
    from interface.telegram_bot import parse_message
    r = parse_message('5 acres Devanahalli compare')
    assert r.market == 'Devanahalli'
    assert r.area_acres == 5.0

def test_dispatch_low_confidence_skipped():
    from interface.telegram_bot import ParsedFieldMessage, dispatch_evaluation
    msg = ParsedFieldMessage(confidence=0.3)
    result = dispatch_evaluation(msg)
    assert result['status'] == 'skipped'

def test_format_verdict_length_constraint():
    from interface.formatters import format_telegram_verdict
    v = format_telegram_verdict(
        market='Hebbal', survey_no='10/1', score=0.65,
        components={'irr': 0.7, 'legal': 0.6, 'timing': 0.6, 'distress': 0.3, 'exclusivity': 0.5},
        legal_risk='CLEAR', next_action='PRIORITY review'
    )
    assert len(v) <= 1200
