"""
RE_OS — PR Tools (Sprint 53 — PR & Brand Department)
MarketPositioningTool: pure Python, no LLM. Generates positioning statements
based on market data, PSF comparisons, and competitive landscape.
"""


def market_positioning_tool(
    market: str,
    avg_psf: float,
    competitor_psf_range: tuple[float, float],
    grade_a_count: int,
) -> str:
    """Generate a market positioning statement.

    Uses quantitative data to determine whether this market positions as
    premium, value, or emerging — without any LLM call.

    Args:
        market: Micro-market name (Yelahanka, Devanahalli, Hebbal)
        avg_psf: Average listing PSF in this market
        competitor_psf_range: (low, high) PSF range of Grade A competitors
        grade_a_count: Number of Grade A developers active in this market

    Returns:
        A positioning statement string like:
        "Yelahanka positions as a VALUE market — PSF ₹7,200 is 28% below
         Grade A avg of ₹10,000, with 4 active developers driving competition."
    """
    if not competitor_psf_range or competitor_psf_range[1] <= 0:
        return _fallback_positioning(market)

    low, high = competitor_psf_range
    competitor_avg = (low + high) / 2.0

    if competitor_avg <= 0:
        return _fallback_positioning(market)

    psf_ratio = avg_psf / competitor_avg

    if psf_ratio >= 1.15:
        tier = "PREMIUM"
        narrative = "commands a premium over Grade A competitors"
        gap_pct = round((psf_ratio - 1.0) * 100)
    elif psf_ratio >= 0.85:
        tier = "COMPETITIVE"
        narrative = "sits within Grade A pricing bands"
        gap_pct = round(abs(1.0 - psf_ratio) * 100)
    else:
        tier = "VALUE"
        narrative = "priced below Grade A — represents value-entry opportunity"
        gap_pct = round((1.0 - psf_ratio) * 100)

    dev_clause = (
        f", with {grade_a_count} Grade A developers active"
        if grade_a_count > 0
        else ""
    )

    return (
        f"{market} positions as a {tier} market — "
        f"{narrative} (~{gap_pct}% gap from ₹{competitor_avg:,.0f}){dev_clause}."
    )


def _fallback_positioning(market: str) -> str:
    """Fallback when competitor data is unavailable."""
    return (
        f"{market} — emerging market with limited Grade A comparables. "
        "Positioning TBD as more transaction data becomes available."
    )
