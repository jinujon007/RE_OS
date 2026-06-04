import pytest
pytestmark = pytest.mark.unit

from utils.output_validator import validate_intel_output


def test_clean_output_passes():
    r = validate_intel_output("PSF is ₹6,500 in Yelahanka", "Yelahanka")
    assert r.passed is True
    assert r.warnings == []


def test_hallucination_phrase_detected():
    r = validate_intel_output("As of my knowledge cutoff, PSF is ₹6,500", "Yelahanka")
    assert r.passed is False
    assert r.has_hallucination_markers is True


def test_psf_too_low_flagged():
    r = validate_intel_output("Entry at ₹500 PSF in Yelahanka", "Yelahanka")
    assert r.passed is False
    assert r.psf_values_in_range is False


def test_psf_too_high_flagged():
    r = validate_intel_output("PSF at ₹50,000 per sq ft", "Yelahanka")
    assert r.passed is False
    assert r.psf_values_in_range is False


def test_valid_psf_passes():
    r = validate_intel_output("Price at ₹6,500 psf", "Yelahanka")
    assert r.passed is True
    assert r.psf_values_in_range is True


def test_unknown_market_flagged():
    r = validate_intel_output("PSF trending at ₹6,500 in an unknown locality", "Yelahanka")
    assert r.passed is True
    assert r.market_references_valid is True


def test_known_market_passes():
    r = validate_intel_output("Analysis for Devanahalli market", "Devanahalli")
    assert r.passed is True
    assert r.market_references_valid is True


def test_empty_text_passes():
    r = validate_intel_output("", "Yelahanka")
    assert r.passed is True
    assert r.warnings == []
