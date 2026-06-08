from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _engine_for_score(row):
    engine = MagicMock()
    conn = MagicMock()
    conn.execute.side_effect = [MagicMock(fetchone=MagicMock(return_value=row)), None]
    engine.begin.return_value.__enter__.return_value = conn
    return engine


def test_score_formula_weights_correct():
    from utils.distressed_developer import compute_developer_distress_score

    row = MagicMock(stall_ratio=0.4, nclt_flag=1.0, bda_flag=0.0)
    with patch("utils.distressed_developer.get_engine", return_value=_engine_for_score(row)):
        score = compute_developer_distress_score("Brigade", "Yelahanka")

    assert score == pytest.approx(0.57, rel=1e-4)


def test_score_clamped_at_1():
    from utils.distressed_developer import compute_developer_distress_score

    row = MagicMock(stall_ratio=2.0, nclt_flag=1.0, bda_flag=1.0)
    with patch("utils.distressed_developer.get_engine", return_value=_engine_for_score(row)):
        score = compute_developer_distress_score("Prestige", "Yelahanka")

    assert score == 1.0


def test_score_zero_when_no_signals():
    from utils.distressed_developer import compute_developer_distress_score

    row = MagicMock(stall_ratio=0.0, nclt_flag=0.0, bda_flag=0.0)
    with patch("utils.distressed_developer.get_engine", return_value=_engine_for_score(row)):
        score = compute_developer_distress_score("Sobha", "Hebbal")

    assert score == 0.0


def test_score_zero_when_input_blank():
    from utils.distressed_developer import compute_developer_distress_score

    assert compute_developer_distress_score("", "Yelahanka") == 0.0
    assert compute_developer_distress_score("Brigade", "") == 0.0
