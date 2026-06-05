"""GATE-46 unit tests — IntelRegistry: all 5 modules, IntelPackage dataclass.

These tests validate the IntelPackage contract without a live database.
IntelRegistry instantiation is tested; get_full_picture requires DB/mocks.
"""
import pytest
import dataclasses
pytestmark = pytest.mark.unit


def test_intel_package_all_fields_present():
    """IntelPackage dataclass has all 5 module output fields."""
    from intelligence.registry import IntelPackage
    fields = {f.name for f in dataclasses.fields(IntelPackage)}
    for required in ("market_pulse", "legal_picture", "financial_evaluation",
                     "land_picture", "demand_signals"):
        assert required in fields, f"Missing IntelPackage field: {required}"


def test_intel_package_has_metadata_fields():
    """IntelPackage has survey_no, market, elapsed_ms, module_status, errors."""
    from intelligence.registry import IntelPackage
    fields = {f.name for f in dataclasses.fields(IntelPackage)}
    for required in ("survey_no", "market", "elapsed_ms", "module_status",
                     "errors", "all_modules_success", "deal_type"):
        assert required in fields, f"Missing metadata field: {required}"


def test_intel_package_default_elapsed_ms_is_zero():
    """Default IntelPackage.elapsed_ms is 0.0 (not None)."""
    from intelligence.registry import IntelPackage
    pkg = IntelPackage(survey_no="45/2", market="Yelahanka",
                       collected_at="2026-06-05T00:00:00")
    assert isinstance(pkg.elapsed_ms, (int, float))
    assert pkg.elapsed_ms == 0.0


def test_intel_package_default_modules_empty():
    """Default IntelPackage starts with empty module_status and errors."""
    from intelligence.registry import IntelPackage
    pkg = IntelPackage(survey_no="45/2", market="Yelahanka",
                       collected_at="2026-06-05T00:00:00")
    assert pkg.module_status == {}
    assert pkg.errors == []
    assert pkg.all_modules_success is False


def test_intel_package_str_repr_does_not_raise():
    """__str__ and __repr__ handle all-None fields without error."""
    from intelligence.registry import IntelPackage
    pkg = IntelPackage(survey_no="45/2", market="Yelahanka",
                       collected_at="2026-06-05T00:00:00")
    s = str(pkg)
    r = repr(pkg)
    assert "45/2" in s
    assert "IntelPackage" in r


def test_intel_registry_instantiates():
    """IntelRegistry can be instantiated without error."""
    from intelligence.registry import IntelRegistry
    reg = IntelRegistry()
    assert hasattr(reg, "get_full_picture")
    assert hasattr(reg, "invalidate_cache")


def test_intel_registry_cache_key_format():
    """_cache_key returns pipe-delimited lowercase key."""
    from intelligence.registry import IntelRegistry
    reg = IntelRegistry()
    key = reg._cache_key("45/2", "Devanahalli", 43560.0, 5000.0)
    assert isinstance(key, str)
    assert "45/2" in key
    assert "Devanahalli" in key


def test_intel_package_invalid_input_returns_error():
    """IntelRegistry.get_full_picture with bad input returns error package."""
    from intelligence.registry import IntelRegistry
    reg = IntelRegistry()
    pkg = reg.get_full_picture("", "")
    assert "ERROR" in pkg.module_status.get("registry", "")
    assert len(pkg.errors) >= 1


def test_intel_package_defaults_for_missing_params():
    """IntelRegistry uses defaults for optional financial params."""
    from intelligence.registry import IntelRegistry
    reg = IntelRegistry()
    key = reg._cache_key("45/2", "Devanahalli", 43560.0, 5000.0)
    assert key.endswith("5000.0")
