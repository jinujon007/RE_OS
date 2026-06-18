"""Tests for DeveloperAliasResolver (T-1196)."""

import pytest

pytestmark = pytest.mark.unit


class TestDeveloperAliasResolver:
    def test_alias_resolver_maps_brigade_variants(self):
        from utils.developer_alias import DeveloperAliasResolver
        variants = ["Brigade Enterprises", "Brigade Group", "Brigade Realty",
                     "Brigade Properties", "Brigade Infra", "M/s Brigade"]
        for v in variants:
            result = DeveloperAliasResolver.canonical(v)
            assert result == "Brigade", f"Expected 'Brigade', got '{result}' for variant '{v}'"

    def test_alias_resolver_returns_raw_on_no_match(self):
        from utils.developer_alias import DeveloperAliasResolver
        result = DeveloperAliasResolver.canonical("Unknown Developer Ltd")
        assert result == "Unknown Developer Ltd"

    def test_alias_resolver_case_insensitive(self):
        from utils.developer_alias import DeveloperAliasResolver
        cases = ["brigade enterprises", "BRIGADE GROUP", "Brigade Realty"]
        for c in cases:
            result = DeveloperAliasResolver.canonical(c)
            assert result == "Brigade", f"Expected 'Brigade', got '{result}' for case variant '{c}'"

    def test_alias_resolver_no_false_positive_substring(self):
        from utils.developer_alias import DeveloperAliasResolver
        result = DeveloperAliasResolver.canonical("Brigadier Realty")
        assert result == "Brigadier Realty", f"Substring match triggered: got '{result}'"

    def test_alias_resolver_empty_string(self):
        from utils.developer_alias import DeveloperAliasResolver
        assert DeveloperAliasResolver.canonical("") == ""

    def test_alias_resolver_reset_clears_cache(self):
        from utils.developer_alias import DeveloperAliasResolver
        DeveloperAliasResolver.reset()
        result = DeveloperAliasResolver.canonical("Brigade Enterprises")
        assert result == "Brigade"

    def test_alias_resolver_prestige_maps_correctly(self):
        from utils.developer_alias import DeveloperAliasResolver
        for v in ["Prestige Estates", "Prestige Group", "Prestige Constructions", "Prestige Properties"]:
            assert DeveloperAliasResolver.canonical(v) == "Prestige"


# ── T-1234: Expanded developer aliases ───────────────────────────────────────


def test_developer_aliases_has_10_entries():
    from config.settings import DEVELOPER_ALIASES
    assert len(DEVELOPER_ALIASES) >= 10
    expected_keys = {"Brigade", "Prestige", "Sobha", "Godrej Properties",
                     "Puravankara", "Mantri Developers", "Total Environment",
                     "Assetz", "Mahindra Lifespace", "Concorde"}
    assert expected_keys.issubset(DEVELOPER_ALIASES.keys())


def test_godrej_canonical_resolution():
    from utils.developer_alias import DeveloperAliasResolver
    DeveloperAliasResolver.reset()
    for v in ["Godrej", "Godrej Realty", "GPDL"]:
        result = DeveloperAliasResolver.canonical(v)
        assert result == "Godrej Properties", f"Expected 'Godrej Properties', got '{result}' for '{v}'"


def test_puravankara_provident_variant_resolves():
    from utils.developer_alias import DeveloperAliasResolver
    DeveloperAliasResolver.reset()
    for v in ["Puravankara Projects", "Puravankara Limited", "Provident", "Provident Housing"]:
        result = DeveloperAliasResolver.canonical(v)
        assert result == "Puravankara", f"Expected 'Puravankara', got '{result}' for '{v}'"


def test_alias_resolver_reload_picks_up_new_settings():
    from utils.developer_alias import DeveloperAliasResolver
    DeveloperAliasResolver.reset()
    result = DeveloperAliasResolver.canonical("Total Env")
    assert result == "Total Environment", f"Expected 'Total Environment', got '{result}'"
    result = DeveloperAliasResolver.canonical("Mantri Corp")
    assert result == "Mantri Developers", f"Expected 'Mantri Developers', got '{result}'"
    result = DeveloperAliasResolver.canonical("Assetz Property")
    assert result == "Assetz", f"Expected 'Assetz', got '{result}'"
