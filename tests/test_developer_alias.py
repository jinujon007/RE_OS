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
