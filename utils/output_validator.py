from __future__ import annotations
import re
from dataclasses import dataclass, field
from loguru import logger

from config.settings import TARGET_MARKETS

__all__ = ["ValidationResult", "validate_intel_output"]


@dataclass
class ValidationResult:
    passed: bool
    warnings: list[str] = field(default_factory=list)
    market_references_valid: bool = True
    psf_values_in_range: bool = True
    has_hallucination_markers: bool = False


_HALLUCINATION_PHRASES = [
    "as of my knowledge cutoff",
    "i don't have access",
    "i cannot confirm",
    "i don't have data",
    "as an ai",
    "my training data",
]

_PSF_PATTERN = re.compile(r"\u20b9\s*([\d,]+)\s*(?:psf|per\s*sq)", re.IGNORECASE)

_PSF_MIN = 1500.0
_PSF_MAX = 30000.0


def validate_intel_output(text: str, market: str) -> ValidationResult:
    if not text:
        return ValidationResult(passed=True)

    warnings = []
    text_lower = text.lower()

    found_phrases = [p for p in _HALLUCINATION_PHRASES if p in text_lower]
    if found_phrases:
        warnings.append(f"HALLUCINATION markers: {found_phrases}")

    valid_markets = [m.lower().strip() for m in TARGET_MARKETS]
    mentioned_markets = re.findall(r"\b(yelahanka|devanahalli|hebbal)\b", text_lower)
    invalid = [m for m in mentioned_markets if m not in valid_markets]
    if invalid:
        warnings.append(f"Unknown market references: {invalid}")

    psf_values = [float(v.replace(",", "")) for v in _PSF_PATTERN.findall(text)]
    bad_psf = [v for v in psf_values if not (_PSF_MIN <= v <= _PSF_MAX)]
    if bad_psf:
        warnings.append(f"PSF values out of range [{_PSF_MIN}–{_PSF_MAX}]: {bad_psf}")

    passed = len(warnings) == 0
    result = ValidationResult(
        passed=passed,
        warnings=warnings,
        has_hallucination_markers=bool(found_phrases),
        psf_values_in_range=not bool(bad_psf),
        market_references_valid=not bool(invalid),
    )
    if warnings:
        logger.warning(
            f"[OutputValidator] {len(warnings)} warnings for {market}: {warnings}"
        )
    return result
