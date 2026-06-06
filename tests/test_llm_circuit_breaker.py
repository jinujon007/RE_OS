"""T-952: LLM circuit breaker tests."""
import pytest
import time
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def test_circuit_opens_after_3_failures():
    from config.llm_router import _record_failure, _get_circuit_state, _CIRCUIT_LOCK, _CIRCUIT_STATE
    _CIRCUIT_STATE.clear()
    provider = "test_provider_a"
    for _ in range(3):
        _record_failure(provider)
    state = _get_circuit_state(provider)
    assert state["circuit"] == "OPEN"


def test_circuit_blocks_when_open():
    from config.llm_router import _record_failure, _is_excluded, _clear_excluded
    provider = "test_provider_b"
    _clear_excluded()
    for _ in range(3):
        _record_failure(provider)
    assert _is_excluded(provider)


def test_circuit_half_open_allows_trial():
    from config.llm_router import (_record_failure, _get_circuit_state,
                                   _CIRCUIT_HALF_OPEN_SECONDS, _CIRCUIT_STATE)
    _CIRCUIT_STATE.clear()
    provider = "test_provider_c"
    for _ in range(3):
        _record_failure(provider)
    state = _get_circuit_state(provider)
    assert state["circuit"] == "OPEN"
    state["open_since"] = time.time() - _CIRCUIT_HALF_OPEN_SECONDS - 1
    state = _get_circuit_state(provider)
    assert state["circuit"] == "HALF_OPEN"


def test_circuit_closes_on_success():
    from config.llm_router import _record_failure, _record_success, _get_circuit_state, _CIRCUIT_STATE
    _CIRCUIT_STATE.clear()
    provider = "test_provider_d"
    for _ in range(3):
        _record_failure(provider)
    state = _get_circuit_state(provider)
    assert state["circuit"] == "OPEN"
    _record_success(provider)
    state = _get_circuit_state(provider)
    assert state["circuit"] == "CLOSED"


def test_circuit_resets_on_clear():
    """_exclude adds to excluded set; _clear_excluded clears it (not circuit state)."""
    from config.llm_router import _exclude, _is_excluded, _clear_excluded, _CIRCUIT_STATE
    _CIRCUIT_STATE.clear()
    provider = "test_provider_e"
    _clear_excluded()
    _exclude(provider)
    assert _is_excluded(provider)
    _clear_excluded()
    assert not _is_excluded(provider)


def test_health_llm_includes_circuit_state():
    from config.llm_router import get_circuit_states, _record_failure, _CIRCUIT_STATE
    _CIRCUIT_STATE.clear()
    _record_failure("groq")
    _record_failure("groq")
    _record_failure("groq")
    states = get_circuit_states()
    assert "groq" in states
    assert states["groq"]["circuit_state"] == "OPEN"
    assert states["groq"]["failure_count"] >= 3
    assert states.get("cerebras", {}).get("circuit_state") == "CLOSED"
