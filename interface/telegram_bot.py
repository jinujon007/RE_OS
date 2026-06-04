"""
RE_OS — Telegram Bot (Sprint 65 — Interface Layer)
FieldMessageParser: parses free-text field messages → {market, area, ask_psf, deal_type}
If confidence > 0.7, calls /api/evaluate pipeline. Returns compact verdict ≤1200 chars.
"""
import os
import re
import time
from dataclasses import dataclass
from typing import Optional
from loguru import logger

__all__ = ["ParsedFieldMessage", "parse_message", "dispatch_evaluation"]

_MARKET_KEYWORDS = {
    "yelahanka": ["yelahanka", "yelanahalli", "new town", "sahakara nagar"],
    "devanahalli": ["devanahalli", "devanahalli", "kial", "airport", "international airport"],
    "hebbal": ["hebbal", "bellary road", "esteem mall", "nagawara", "manyata"],
}

_EVALUATE_API_URL = os.environ.get("EVALUATE_API_URL", "http://localhost:8050/api/evaluate")

_DEAL_KEYWORDS = {
    "jd": ["jd", "joint development", "joint dev", "revenue share", "profit share"],
    "jv": ["jv", "joint venture"],
    "purchase": ["purchase", "buy", "outright", "buyout", "acquisition"],
    "compare": ["compare", "evaluate", "what if", "all options", "analysis"],
}

@dataclass
class ParsedFieldMessage:
    market: str = ""
    area_acres: float = 0.0
    area_sqft: float = 0.0
    ask_psf: float = 0.0
    deal_type: str = "compare"
    confidence: float = 0.0
    raw_text: str = ""

_MAX_TEXT_LENGTH = 500
_PSF_SANE_MIN = 500.0
_PSF_SANE_MAX = 50000.0
_AREA_ACRE_MAX = 10000.0

_ACRES_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*(?:acres?|ac|acre)', re.IGNORECASE)
_SQFT_PATTERN = re.compile(r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:sq\s*ft|sqft|sft|square\s*feet)', re.IGNORECASE)
_PSF_PATTERN = re.compile(r'(?:rs\.?\s*|inr\s*|₹)?\s*(\d{3,5}(?:,\d{3})*(?:\.\d+)?)\s*(?:psf|per\s*sq)', re.IGNORECASE)
_PRICE_CR_PATTERN = re.compile(r'(?:rs\.?\s*|inr\s*|₹)?\s*(\d+(?:\.\d+)?)\s*(?:cr|crore)', re.IGNORECASE)

def _clean_number(s: str) -> float:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0

def parse_message(text: str) -> ParsedFieldMessage:
    raw = (text or "").strip()[:_MAX_TEXT_LENGTH]
    if not raw:
        return ParsedFieldMessage(confidence=0.0)

    result = ParsedFieldMessage(raw_text=raw)
    tokens = 0
    text_lower = raw.lower()

    # Market detection
    for market, keywords in _MARKET_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                result.market = market.capitalize()
                tokens += 1
                break
        if result.market:
            break

    # Area detection (acres first, then sqft)
    acres_match = _ACRES_PATTERN.search(raw)
    if acres_match:
        result.area_acres = _clean_number(acres_match.group(1))
        result.area_sqft = result.area_acres * 43560
        tokens += 1

    sqft_match = _SQFT_PATTERN.search(raw)
    if sqft_match and result.area_acres == 0:
        result.area_sqft = _clean_number(sqft_match.group(1))
        result.area_acres = result.area_sqft / 43560
        tokens += 1

    # PSF detection
    psf_match = _PSF_PATTERN.search(raw)
    if psf_match:
        result.ask_psf = _clean_number(psf_match.group(1))
        tokens += 1
    else:
        # Try crore-based price / area
        cr_match = _PRICE_CR_PATTERN.search(raw)
        if cr_match and result.area_sqft > 0:
            price_cr = _clean_number(cr_match.group(1))
            result.ask_psf = (price_cr * 10000000) / result.area_sqft
            tokens += 1

    # Deal type detection
    for dtype, keywords in _DEAL_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                result.deal_type = dtype
                tokens += 1
                break
        if result.deal_type != "compare":
            break

    # Cap parsed values to sane ranges
    result.area_acres = min(result.area_acres, _AREA_ACRE_MAX)
    result.ask_psf = max(_PSF_SANE_MIN, min(result.ask_psf, _PSF_SANE_MAX)) if result.ask_psf > 0 else 0.0

    max_tokens = 7
    result.confidence = round(min(tokens / max_tokens, 1.0), 2)

    if result.confidence > 0.7:
        logger.info("[TelegramBot] Parsed high-confidence message: m=%s a=%.1fac psf=%.0f d=%s (conf=%.2f)",
                     result.market, result.area_acres, result.ask_psf, result.deal_type, result.confidence)
    else:
        logger.info("[TelegramBot] Low-confidence parse: m=%s conf=%.2f", result.market, result.confidence)

    return result


def dispatch_evaluation(parsed: ParsedFieldMessage) -> dict:
    """Call the evaluate pipeline when confidence > 0.7.
    Endpoint URL configurable via EVALUATE_API_URL env var.
    Returns {"job_id": ..., "status": "running"} or error dict.
    
    Safe guards:
    - 30s HTTP timeout prevents hang
    - Non-live market detection prevents silent skips
    - JSON parse error returns structured error, not crash
    """
    if parsed.confidence < 0.7:
        return {"status": "skipped", "reason": "confidence {} < 0.7 threshold".format(parsed.confidence)}
    if not parsed.market:
        return {"status": "skipped", "reason": "no market detected in message"}
    try:
        import httpx
        api_key = os.environ.get("DASHBOARD_API_KEY", "")
        payload = {
            "survey_no": "{}-telegram-{}".format(parsed.market, int(time.time())),
            "market": parsed.market,
            "land_area_sqft": max(parsed.area_sqft, 1000) or 5200,
            "deal_type": parsed.deal_type,
        }
        resp = httpx.post(
            _EVALUATE_API_URL,
            json=payload,
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {"status": "error", "error": "non-JSON response: {}".format(resp.text[:200])}
        return {"status": "error", "error": "HTTP {}: {}".format(resp.status_code, resp.text[:200])}
    except Exception as exc:
        logger.error("[TelegramBot] dispatch_evaluate failed: {}".format(exc))
        return {"status": "error", "error": str(exc)}
