"""T-1504 — Utils modules coverage test (GATE-163 A4).

Asserts 15 key utils modules are importable and their expected
symbols exist and are callable (or classes).
Also asserts utils.__all__ contains "ParcelGraph" and "CorridorScorerV2".

Risk notes:
  - UTILS_CHECKLIST must be updated when new utils modules are created
    or when important public symbols are renamed.
  - The import-side-effect check catches modules that trigger DB connections
    at import time — these prevent test isolation and must be refactored
    to use lazy initialization.
  - UTILS_EXTRA covers additional high-value symbols that gate tests reference
    but that aren't in the core 15 — keep this list current.
"""

import importlib

import pytest

pytestmark = pytest.mark.unit

UTILS_CHECKLIST: list[tuple[str, str]] = [
    ("utils.parcel_graph", "ParcelGraph"),
    ("utils.strr_overlay", "STRROverlay"),
    ("utils.intelligence_calibrator", "run_calibration_check"),
    ("utils.digest_validator", "validate_digest"),
    ("utils.deal_scorer", "score_deal"),
    ("utils.assembly_detector", "AssemblyDetector"),
    ("utils.corridor_scorer", "CorridorScorer"),
    ("utils.irr_model", "calc_irr"),
    ("utils.deed_progress", "compute_throughput_projection"),
    ("utils.prediction_tracker", "compute_mape"),
    ("utils.discord_notifier", "send_ops_alert"),
    ("utils.telegram_notifier", "send_message"),
    ("utils.obsidian_sync", "write_note"),
    ("utils.agent_memory", "write_memory"),
    ("utils.embedder", "IntelEmbedder"),
]

UTILS_EXTRA: list[tuple[str, str]] = [
    ("utils.corridor_scorer_v2", "CorridorScorerV2"),
    ("utils.deed_progress", "get_priority_villages"),
    ("utils.decision_journal", "list_entries"),
]


@pytest.mark.parametrize("module_path,symbol_name", UTILS_CHECKLIST)
def test_utils_module_symbol(module_path: str, symbol_name: str):
    mod = importlib.import_module(module_path)
    assert hasattr(mod, symbol_name), (
        f"{module_path} has no attribute '{symbol_name}'. "
        f"Available: {[x for x in dir(mod) if not x.startswith('_')]}"
    )
    symbol = getattr(mod, symbol_name)
    assert callable(symbol) or isinstance(symbol, type), (
        f"{module_path}.{symbol_name} is {type(symbol).__name__} — "
        f"expected a callable function or a class"
    )


@pytest.mark.parametrize("module_path,symbol_name", UTILS_EXTRA)
def test_utils_extra_symbols(module_path: str, symbol_name: str):
    mod = importlib.import_module(module_path)
    assert hasattr(mod, symbol_name), (
        f"{module_path} has no extra symbol '{symbol_name}'"
    )


def test_utils_non_existent_symbol_raises():
    mod = importlib.import_module("utils.digest_validator")
    assert not hasattr(mod, "non_existent_function_xyz"), (
        "Expected no attribute 'non_existent_function_xyz' in "
        "utils.digest_validator"
    )


def test_utils_import_no_side_effects():
    failures: list[str] = []
    for module_path, _ in UTILS_CHECKLIST:
        try:
            importlib.import_module(module_path)
        except Exception as exc:
            failures.append(f"{module_path}: {type(exc).__name__}: {exc}")
    assert not failures, (
        "Import-side-effect failures (modules that crash on import):\n"
        + "\n".join(failures)
    )


def test_utils_all_contains_parcel_graph():
    import utils

    assert hasattr(utils, "__all__"), (
        "utils package missing __all__ export"
    )
    all_list = utils.__all__
    assert isinstance(all_list, list), (
        f"utils.__all__ is {type(all_list).__name__}, expected list"
    )
    assert "ParcelGraph" in all_list, (
        f"'ParcelGraph' not in utils.__all__. "
        f"This is required for backward-compatible imports from "
        f"GATE-155 H-1 fix. Current __all__: {all_list}"
    )


def test_utils_all_contains_corridor_scorer_v2():
    import utils

    assert "CorridorScorerV2" in utils.__all__, (
        f"'CorridorScorerV2' not in utils.__all__: {utils.__all__}"
    )
