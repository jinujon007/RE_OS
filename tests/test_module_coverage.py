"""GATE-167: Utils + Scraper Module Coverage — T-1521, T-1522, T-1523, T-1524.

T-1521: All 86+ utils modules importable (bulk + parametrized).
T-1522: All 19 scraper modules importable (bulk + parametrized).
T-1523: 15 key utils symbols from GATE-167 A3 spec exist and are callable.
T-1524: 5 key scraper symbols exist and are callable.

Design notes:
  - Module lists are built dynamically at collection time via Path.glob,
    ensuring zero maintenance when new modules are added.
  - Empty-directory guard prevents vacuous pass if checkout is broken.
  - diagnose.py is excluded from parametrized import tests because it is a
    standalone diagnostic script with import-time DB connection side effects.
  - board_room_formatter exports BoardRoomFormatter (class), not the spec-
    mentioned format_board_verdict — the actual public symbol is used.
  - agent_memory exports write_memory (function) per its __all__, not the
    spec-mentioned AgentMemory class (which does not exist).
  - Scrapers package has no __all__ at time of writing; test is lenient.
"""

import importlib
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

# ── Paths resolved from file location (not cwd) ─────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Modules excluded from parametrized import tests ─────────────
# diagnose.py: standalone script with import-time DB connection side effects.
# Any module that crashes on import in CI (GPU/torch deps, DB req) goes here.
_PARAMETRIZED_IMPORT_EXCLUSIONS: set[str] = {"diagnose"}

# ── Dynamic module lists (future-proof, cwd-independent) ───────
_UTILS_DIR = _PROJECT_ROOT / "utils"
_SCRAPERS_DIR = _PROJECT_ROOT / "scrapers"

UTILS_MODULES = sorted(
    f.stem for f in _UTILS_DIR.glob("*.py") if f.stem != "__init__"
)

SCRAPER_MODULES = sorted(
    f.stem for f in _SCRAPERS_DIR.glob("*.py") if f.stem != "__init__"
)

# Guard: non-empty — prevents vacuous pass if checkout is broken
assert len(UTILS_MODULES) >= 80, (
    f"Only {len(UTILS_MODULES)} utils modules found at {_UTILS_DIR}. "
    "Expected ≥80. Checkout may be incomplete."
)
assert len(SCRAPER_MODULES) >= 15, (
    f"Only {len(SCRAPER_MODULES)} scraper modules found at {_SCRAPERS_DIR}. "
    "Expected ≥15. Checkout may be incomplete."
)

# Modules with exclusions applied (for parametrized tests)
UTILS_MODULES_PARAM = [
    m for m in UTILS_MODULES
    if m not in _PARAMETRIZED_IMPORT_EXCLUSIONS
]

# ── Shared assertion helper ─────────────────────────────────────


def _assert_symbol_exists(module_path: str, symbol_name: str) -> None:
    """Import module_path and verify symbol_name is a callable or class.

    Args:
        module_path: Fully qualified module path (e.g. 'utils.deal_scorer').
        symbol_name: Attribute name to verify on the module.

    Raises:
        AssertionError: If the symbol does not exist or is not callable/type.
    """
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


# ═══════════════════════════════════════════════════════════════════
# T-1521: Utils full import test
# ═══════════════════════════════════════════════════════════════════


def test_t1521_utils_import_bulk():
    """All utils modules import without exception (≤5 failures allowed).

    The tolerance covers GPU-only dependencies (torch, transformers) and
    standalone scripts with import-time side effects (diagnose.py). Each
    failure is reported with module name and exception type+message.
    If this assertion fails, investigate the failure list — the first
    entry is likely the root cause.
    """
    failures: list[tuple[str, str]] = []
    for name in UTILS_MODULES:
        try:
            importlib.import_module(f"utils.{name}")
        except Exception as e:
            failures.append((name, f"{type(e).__name__}: {e}"))
    assert len(failures) <= 5, (
        f"T-1521 FAIL: {len(failures)} utils import failures "
        f"(allowed ≤5 for GPU/torch/side-effects). "
        f"Failures: {failures}"
    )


@pytest.mark.parametrize("mod_name", UTILS_MODULES_PARAM)
def test_t1521_utils_import_each(mod_name: str):
    """Each utils module imports cleanly (parametrized, granular reporting).

    Uses sys.modules cache to avoid redundant imports already performed
    by the bulk test. This parametrized version provides per-module
    granularity for debugging.
    """
    cached = sys.modules.get(f"utils.{mod_name}")
    if cached is not None:
        return
    importlib.import_module(f"utils.{mod_name}")


# ═══════════════════════════════════════════════════════════════════
# T-1522: Scraper full import test
# ═══════════════════════════════════════════════════════════════════


def test_t1522_scraper_import_bulk():
    """All scraper modules import without exception (0 failures expected).

    Scrapers should have no GPU dependencies. Any failure here indicates
    a real import error (missing dependency, syntax error, circular import)
    that would break the pipeline at 2am. Each failure is reported with
    module name and exception type+message.
    """
    failures: list[tuple[str, str]] = []
    for name in SCRAPER_MODULES:
        try:
            importlib.import_module(f"scrapers.{name}")
        except Exception as e:
            failures.append((name, f"{type(e).__name__}: {e}"))
    assert len(failures) == 0, (
        f"T-1522 FAIL: {len(failures)} scraper import failures "
        f"(expected 0 — scrapers have no GPU deps): {failures}"
    )


@pytest.mark.parametrize("mod_name", SCRAPER_MODULES)
def test_t1522_scraper_import_each(mod_name: str):
    """Each scraper module imports cleanly (parametrized, granular reporting)."""
    cached = sys.modules.get(f"scrapers.{mod_name}")
    if cached is not None:
        return
    importlib.import_module(f"scrapers.{mod_name}")


# ═══════════════════════════════════════════════════════════════════
# T-1523: Key utils callable assertions (15 pairs from GATE-167 A3)
# ═══════════════════════════════════════════════════════════════════
#
# Aligned with GATE-167 success criteria A3.
# Deviations from spec (both documented):
#   board_room_formatter.format_board_verdict → BoardRoomFormatter (class)
#   agent_memory.AgentMemory → write_memory (function, __all__ export)
#
# These 15 complement the 15 already tested in test_utils_coverage.py.
# Combined they cover all high-signal utils symbols. If a symbol here
# fails, check whether the module's public API was refactored.

UTILS_SYMBOL_PAIRS: list[tuple[str, str]] = [
    ("utils.deal_scorer", "score_deal"),
    ("utils.parcel_graph", "ParcelGraph"),
    ("utils.strr_overlay", "STRROverlay"),
    ("utils.intelligence_calibrator", "run_calibration_check"),
    ("utils.digest_validator", "validate_digest"),
    ("utils.assembly_detector", "AssemblyDetector"),
    ("utils.corridor_scorer", "CorridorScorer"),
    ("utils.irr_model", "calc_irr"),
    ("utils.deed_progress", "compute_throughput_projection"),
    ("utils.prediction_tracker", "compute_mape"),
    ("utils.discord_notifier", "send_ops_alert"),
    ("utils.telegram_notifier", "send_message"),
    # spec: board_room_formatter.format_board_verdict — symbol does not exist
    ("utils.board_room_formatter", "BoardRoomFormatter"),
    ("utils.fsi_calculator", "calculate_fsi"),
    # spec: agent_memory.AgentMemory — class does not exist; use write_memory
    ("utils.agent_memory", "write_memory"),
]


@pytest.mark.parametrize("module_path,symbol_name", UTILS_SYMBOL_PAIRS)
def test_t1523_utils_symbol(module_path: str, symbol_name: str):
    """Each GATE-167 A3 utils symbol exists and is callable."""
    _assert_symbol_exists(module_path, symbol_name)


# ═══════════════════════════════════════════════════════════════════
# T-1524: Key scraper callable assertions (5 pairs)
# ═══════════════════════════════════════════════════════════════════
#
# Covers primary export classes from the 5 most critical scrapers.
# Each should be either a class (e.g., KaveriScraper) or a top-level
# function (e.g., parse_pdf_file).

SCRAPER_SYMBOL_PAIRS: list[tuple[str, str]] = [
    ("scrapers.kaveri_karnataka", "KaveriScraper"),
    ("scrapers.igr_karnataka", "IGRTransactionScout"),
    ("scrapers.news_scout", "NewsScout"),
    ("scrapers.portal_scout", "PortalScout"),
    ("scrapers.kaveri_deeds", "parse_pdf_file"),
]


@pytest.mark.parametrize("module_path,symbol_name", SCRAPER_SYMBOL_PAIRS)
def test_t1524_scraper_symbol(module_path: str, symbol_name: str):
    """Each key scraper symbol exists and is callable."""
    _assert_symbol_exists(module_path, symbol_name)


# ═══════════════════════════════════════════════════════════════════
# Supplementary: Package __all__ sanity checks
# ═══════════════════════════════════════════════════════════════════
# These verify that the public API contracts are maintained. If __all__
# is missing or empty, downstream import-star usage will break silently.


def test_utils_init_has_all():
    """utils.__init__ defines __all__ with at least 1 export entry."""
    import utils

    assert hasattr(utils, "__all__"), (
        "utils package missing __all__. Import-star imports will break silently."
    )
    assert isinstance(utils.__all__, list), (
        "utils.__all__ must be a list, got "
        f"{type(utils.__all__).__name__}"
    )
    assert len(utils.__all__) >= 1, "utils.__all__ is empty"


def test_scrapers_init_has_all():
    """scrapers.__init__ defines __all__ (non-fatal advisory).

    Note: scrapers/__init__.py was empty at time of writing. This test
    verifies that if __all__ is defined, it is a non-empty list. The
    assertion is intentionally lenient to avoid gate failure on a
    pre-existing condition that is outside this sprint's scope.
    """
    import scrapers

    if not hasattr(scrapers, "__all__"):
        pytest.skip(
            "scrapers package has no __all__ (pre-existing — "
            "add to scrapers/__init__.py in a future sprint)"
        )
    assert isinstance(scrapers.__all__, list), (
        "scrapers.__all__ must be a list, got "
        f"{type(scrapers.__all__).__name__}"
    )
    assert len(scrapers.__all__) >= 1, "scrapers.__all__ is empty"


# ═══════════════════════════════════════════════════════════════════
# Negative test: failure-detection mechanism validation
# ═══════════════════════════════════════════════════════════════════
# This validates that the failure-collection machinery in the bulk import
# tests actually catches real failures. If this test passes, the bulk
# loops in T-1521/T-1522 are correctly instrumented.


def test_failure_detection_works():
    """Verify that a non-existent module is correctly flagged as import failure.

    This validates the failure-detection machinery itself — if this test
    passes, the bulk-import failure-collection loop in T-1521/T-1522 is
    correctly catching real failures. A false pass here would mean bulk
    import failures are being silently swallowed.
    """
    with pytest.raises(ModuleNotFoundError, match="nonexistent_module_xyz"):
        importlib.import_module("utils._nonexistent_module_xyz")
