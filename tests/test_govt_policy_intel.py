"""T-1048 unit tests — GovtPolicyIntel."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

pytestmark = pytest.mark.unit


def _mock_db_rows(rows):
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = rows
    mock_eng = MagicMock()
    mock_eng.connect.return_value.__enter__.return_value = mock_conn
    return patch("utils.db.get_engine", return_value=mock_eng)


def _mock_llm_fallback():
    """Patch get_analysis_llm to raise (triggers fallback digest)."""
    return patch(
        "config.llm_router.get_analysis_llm", side_effect=Exception("LLM unavailable")
    )


def test_compute_returns_govt_policy_result():
    from intelligence.govt_policy_intel import GovtPolicyIntel, GovtPolicyResult

    with _mock_db_rows([]), _mock_llm_fallback():
        intel = GovtPolicyIntel(caller="test")
        result = intel.compute("north_bengaluru_aggregate")
        assert isinstance(result, GovtPolicyResult)


def test_north_bengaluru_score_in_range():
    from intelligence.govt_policy_intel import GovtPolicyIntel

    rows = [
        (
            "Metro approved",
            "infrastructure",
            "metro",
            6100.0,
            "construction",
            9,
            "high",
            "long",
            "buy_now",
            "Test",
            "Test",
            True,
            "2026-01-15",
            "2026-06-08 00:00:00+00",
        ),
    ]
    with _mock_db_rows(rows), _mock_llm_fallback():
        intel = GovtPolicyIntel(caller="test")
        result = intel.compute("north_bengaluru_aggregate")
        assert 0.0 <= result.north_bengaluru_score <= 1.0


def test_high_opportunity_count_correct():
    from intelligence.govt_policy_intel import GovtPolicyIntel

    rows = [
        (
            "High impact event",
            "infrastructure",
            "metro",
            1000.0,
            "construction",
            9,
            "high",
            "long",
            "buy_now",
            "Test",
            "Test",
            True,
            "2026-01-15",
            "2026-06-08 00:00:00+00",
        ),
        (
            "Risk event",
            "policy",
            "fsi_revision",
            None,
            "announcement",
            5,
            "risk",
            "medium",
            "monitor",
            "Test risk",
            "Test risk",
            True,
            "2026-05-01",
            "2026-06-07 00:00:00+00",
        ),
    ]
    with _mock_db_rows(rows), _mock_llm_fallback():
        intel = GovtPolicyIntel(caller="test")
        result = intel.compute("north_bengaluru_aggregate")
        assert result.high_opportunity_count >= 1
        assert result.risk_count >= 1


def test_top_infra_events_max_3():
    from intelligence.govt_policy_intel import GovtPolicyIntel

    rows = [
        (
            "Evt {}".format(i),
            "infrastructure",
            "metro",
            100.0,
            "construction",
            9,
            "high",
            "long",
            "buy_now",
            "Test",
            "Test",
            True,
            "2026-01-15",
            "2026-06-08 00:00:00+00",
        )
        for i in range(5)
    ]
    with _mock_db_rows(rows), _mock_llm_fallback():
        intel = GovtPolicyIntel(caller="test")
        result = intel.compute("north_bengaluru_aggregate")
        assert len(result.top_infra_events) <= 3


def test_weekly_digest_nonempty():
    from intelligence.govt_policy_intel import GovtPolicyIntel

    rows = [
        (
            "Metro approved",
            "infrastructure",
            "metro",
            6100.0,
            "construction",
            9,
            "high",
            "long",
            "buy_now",
            "Test",
            "Test",
            True,
            "2026-01-15",
            "2026-06-08 00:00:00+00",
        ),
    ]
    with _mock_db_rows(rows), _mock_llm_fallback():
        intel = GovtPolicyIntel(caller="test")
        result = intel.compute("north_bengaluru_aggregate")
        assert result.weekly_digest, "weekly_digest should be non-empty (fallback)"


def test_compute_zero_on_empty_db():
    from intelligence.govt_policy_intel import GovtPolicyIntel

    with _mock_db_rows([]), _mock_llm_fallback():
        intel = GovtPolicyIntel(caller="test")
        result = intel.compute("north_bengaluru_aggregate")
        assert result.north_bengaluru_score == 0.0
