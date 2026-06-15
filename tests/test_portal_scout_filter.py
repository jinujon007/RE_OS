"""Tests for portal_scout locality filter (_locality_matches_market) and counter.

Verifies:
- Valid localities pass for each market
- Mis-geocoded localities are rejected
- Empty locality passes through (fallback to market name)
- Edge cases: partial substring match, case insensitivity, unknown market
"""

import pytest

pytestmark = pytest.mark.unit


def test_yelahanka_valid_localities():
    from scrapers.portal_scout import _locality_matches_market

    valid = [
        "Yelahanka",
        "yelahanka new town",
        "Yelahanka Old Town",
        "Kodigehalli",
        "Vidyaranyapura",
        "Jalahalli East",
        "Attur Layout",
    ]
    for loc in valid:
        assert _locality_matches_market(loc, "Yelahanka"), (
            f"Should accept {loc!r} for Yelahanka"
        )


def test_devanahalli_valid_localities():
    from scrapers.portal_scout import _locality_matches_market

    valid = [
        "Devanahalli",
        "Devanahalli International Airport",
        "Kempegowda International Airport",
        "Nandi Hills",
    ]
    for loc in valid:
        assert _locality_matches_market(loc, "Devanahalli"), (
            f"Should accept {loc!r} for Devanahalli"
        )


def test_hebbal_valid_localities():
    from scrapers.portal_scout import _locality_matches_market

    valid = [
        "Hebbal",
        "Hebbal Lake",
        "Manyata Tech Park",
        "Nagavara",
        "Thanisandra Main Road",
        "Jakkur Plantation",
    ]
    for loc in valid:
        assert _locality_matches_market(loc, "Hebbal"), (
            f"Should accept {loc!r} for Hebbal"
        )


def test_rejects_misgeocoded_listings():
    from scrapers.portal_scout import _locality_matches_market

    misgeocoded = [
        ("Electronic City, Bangalore", "Devanahalli"),
        ("Kormangala", "Devanahalli"),
        ("Whitefield", "Devanahalli"),
        ("MG Road", "Hebbal"),
        ("Koramangala 5th Block", "Yelahanka"),
        ("Indiranagar", "Hebbal"),
    ]
    for locality, market in misgeocoded:
        assert not _locality_matches_market(locality, market), (
            f"Should reject {locality!r} for {market}"
        )


def test_empty_locality_passes_through():
    from scrapers.portal_scout import _locality_matches_market

    assert _locality_matches_market("", "Devanahalli")
    assert _locality_matches_market(None, "Devanahalli")
    assert _locality_matches_market("  ", "Yelahanka")


def test_exact_market_name_passess():
    from scrapers.portal_scout import _locality_matches_market

    assert _locality_matches_market("Devanahalli", "Devanahalli")
    assert _locality_matches_market("Yelahanka", "Yelahanka")
    assert _locality_matches_market("Hebbal", "Hebbal")


def test_case_insensitive():
    from scrapers.portal_scout import _locality_matches_market

    assert _locality_matches_market("devanahalli international airport", "Devanahalli")
    assert _locality_matches_market("MANYATA TECH PARK", "Hebbal")
    assert _locality_matches_market("Yelahanka New Town", "YELAHANKA")


def test_unknown_market_uses_exact_fallback():
    from scrapers.portal_scout import _locality_matches_market

    assert _locality_matches_market("Whitefield", "Whitefield")
    assert _locality_matches_market("", "Whitefield")
    assert not _locality_matches_market("Electronic City", "Whitefield")


def test_partial_substring_not_false_match():
    from scrapers.portal_scout import _locality_matches_market

    # "yelahanka" in "hebbal" = False. "hebbal" in "yelahanka" = False.
    assert not _locality_matches_market("Yelahanka", "Hebbal")
    assert not _locality_matches_market("Hebbal", "Yelahanka")
