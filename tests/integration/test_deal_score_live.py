from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from tests.integration.conftest import integration

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

pytestmark = [integration]

_TEST_CASES = [
    pytest.param("Yelahanka", 5.0, 1.5, id="yelahanka-5cr-1.5ac"),
    pytest.param("Devanahalli", 3.0, 1.0, id="devanahalli-3cr-1ac"),
    pytest.param("Hebbal", 8.0, 2.0, id="hebbal-8cr-2ac"),
]

_EXPECTED_SIGNALS = {"assembly", "corridor", "strr", "irr", "kill_criteria"}
_VALID_VERDICTS = {"GO", "CAUTIOUS", "NO-GO"}
_VALID_STRR_SIGNALS = {"STRONG", "MODERATE", "WEAK", "unknown"}


@pytest.mark.test_id("G164-A3")
@pytest.mark.integration
@pytest.mark.parametrize("market,land_cost_cr,area_acres", _TEST_CASES)
def test_deal_score_live(market: str, land_cost_cr: float, area_acres: float) -> None:
    """score_deal returns valid structure for each target market.

    Verifies the full return contract:
    - Top-level keys: overall_score, verdict, confidence, signals, reasoning,
      market, land_cost_cr, area_acres, generated_at, metadata.
    - overall_score in [0, 1].
    - verdict in {GO, CAUTIOUS, NO-GO}.
    - confidence > 0 (no complete fallback scenario for known markets).
    - All 5 signal keys present.
    - metadata.strr_signal in valid set.
    - Input fields round-tripped correctly.
    """
    from utils.deal_scorer import score_deal

    result = score_deal(market, land_cost_cr=land_cost_cr, area_acres=area_acres)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    assert "overall_score" in result, f"Missing overall_score: {list(result.keys())}"
    score = result["overall_score"]
    assert isinstance(score, (int, float)), f"overall_score not numeric: {type(score)}"
    assert 0 <= score <= 1, f"overall_score {score} out of [0, 1]"

    assert result["verdict"] in _VALID_VERDICTS, (
        f"Unexpected verdict '{result['verdict']}'; expected one of {_VALID_VERDICTS}"
    )

    confidence = result["confidence"]
    assert confidence > 0, (
        f"confidence must be > 0 for known market '{market}', got {confidence}"
    )

    # Signals
    assert "signals" in result, f"Missing 'signals': {list(result.keys())}"
    for sig in _EXPECTED_SIGNALS:
        assert sig in result["signals"], (
            f"signals missing '{sig}'; present: {list(result['signals'].keys())}"
        )

    # Metadata shape
    assert "metadata" in result, f"Missing 'metadata': {list(result.keys())}"
    meta = result["metadata"]
    assert meta.get("strr_signal") in _VALID_STRR_SIGNALS, (
        f"strr_signal '{meta.get('strr_signal')}' not in {_VALID_STRR_SIGNALS}"
    )

    # Input round-trip
    assert result.get("market") == market, (
        f"market mismatch: expected '{market}', got '{result.get('market')}'"
    )
    assert result.get("land_cost_cr") == land_cost_cr
    assert result.get("area_acres") == area_acres

    # Timestamp
    assert "generated_at" in result, "Missing 'generated_at' timestamp"
    assert isinstance(result["generated_at"], str)

    # Reasoning (may be truncated but must exist)
    assert "reasoning" in result, "Missing 'reasoning'"


@pytest.mark.test_id("G164-A3-fallback")
@pytest.mark.integration
def test_deal_score_fallback() -> None:
    """score_deal handles unknown market gracefully via fallback path.

    An unknown market should still return a valid result dict with minimal
    scores (all signals in fallback) and a verdict present. The function
    must not raise ValueError for unknown markets — only for invalid inputs.
    """
    from utils.deal_scorer import score_deal

    result = score_deal("InvalidMarket", land_cost_cr=5.0, area_acres=1.5)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    assert "verdict" in result, f"Missing 'verdict': {list(result.keys())}"
    assert result["verdict"] in _VALID_VERDICTS, (
        f"Fallback verdict '{result['verdict']}' not in {_VALID_VERDICTS}"
    )

    assert "overall_score" in result
    assert 0 <= result["overall_score"] <= 1

    assert "metadata" in result
    assert result["metadata"].get("strr_signal") in _VALID_STRR_SIGNALS, (
        f"Fallback strr_signal '{result['metadata'].get('strr_signal')}' "
        f"not in {_VALID_STRR_SIGNALS}"
    )

    assert result["market"] == "InvalidMarket"
    assert "generated_at" in result
    assert "reasoning" in result
