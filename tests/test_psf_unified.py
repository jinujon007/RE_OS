"""T-951: Unified PSF tier selection tests (migration 0023)."""
import pytest
pytestmark = pytest.mark.unit


def _simulate_psf_tier(kaveri_count, gv_count, live_listing_count, all_listing_count,
                       kaveri_psf=8000.0, gv_psf=5000.0, live_psf=6500.0, seed_psf=5500.0):
    """Simulates the 4-tier COALESCE cascade logic from migration 0023."""
    if kaveri_count >= 5:
        return (kaveri_psf, 1, 'kaveri_registration')
    if gv_count >= 3:
        return (gv_psf, 2, 'guidance_value')
    if live_listing_count >= 5:
        return (live_psf, 3, 'live_listing')
    if all_listing_count >= 1:
        return (seed_psf, 4, 'seed_listing')
    return (None, None, None)


def test_psf_tier1_kaveri_registration():
    psf, tier, label = _simulate_psf_tier(
        kaveri_count=10, gv_count=0, live_listing_count=5, all_listing_count=10)
    assert tier == 1
    assert label == 'kaveri_registration'
    assert psf == 8000.0


def test_psf_tier2_guidance_value():
    psf, tier, label = _simulate_psf_tier(
        kaveri_count=2, gv_count=5, live_listing_count=10, all_listing_count=20)
    assert tier == 2
    assert label == 'guidance_value'
    assert psf == 5000.0


def test_psf_tier3_live_listing():
    psf, tier, label = _simulate_psf_tier(
        kaveri_count=0, gv_count=1, live_listing_count=10, all_listing_count=15)
    assert tier == 3
    assert label == 'live_listing'
    assert psf == 6500.0


def test_psf_tier4_seed_fallback():
    psf, tier, label = _simulate_psf_tier(
        kaveri_count=0, gv_count=0, live_listing_count=2, all_listing_count=5)
    assert tier == 4
    assert label == 'seed_listing'
    assert psf == 5500.0


def test_psf_tier1_beats_tier2_when_both_have_data():
    psf, tier, label = _simulate_psf_tier(
        kaveri_count=5, gv_count=10, live_listing_count=100, all_listing_count=200)
    assert tier == 1
    assert label == 'kaveri_registration'


def test_psf_tier2_beats_tier3_when_kaveri_insufficient():
    psf, tier, label = _simulate_psf_tier(
        kaveri_count=3, gv_count=3, live_listing_count=100, all_listing_count=200)
    assert tier == 2
    assert label == 'guidance_value'


def test_psf_returns_none_when_no_data():
    psf, tier, label = _simulate_psf_tier(
        kaveri_count=0, gv_count=0, live_listing_count=0, all_listing_count=0)
    assert tier is None
    assert label is None
