"""
RE_OS — Encumbrance Checker (Phase 12 — Legal Department)
Wraps existing Kaveri scraper, queries guidance_values + kaveri_registrations from DB.
Input: market, survey_no (optional)
Returns: avg guidance value PSF, registration count in 180-day window,
avg transaction PSF, guidance gap %; uses DB-first, Kaveri portal fallback.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from loguru import logger

# Encumbrance check window — number of days of registration history to analyse
_ENCUMBRANCE_WINDOW_DAYS: int = 180

# Guidance gap threshold — gap % above this triggers a risk flag
_GUIDANCE_GAP_THRESHOLD_PCT: float = 20.0


@dataclass
class EncumbranceResult:
    market: str
    survey_no: str | None
    avg_guidance_value_psf: float | None
    registration_count_180d: int
    avg_transaction_psf: float | None
    guidance_gap_pct: float | None  # (txn_psf - gv_psf) / gv_psf * 100
    data_source: str                # "db" | "kaveri_portal" | "unavailable"
    risk_flags: list[str]


def check_encumbrance(
    market: str,
    survey_no: str | None = None,
    window_days: int = _ENCUMBRANCE_WINDOW_DAYS,
) -> EncumbranceResult:
    """Check encumbrance status for a market from DB. Falls back to Kaveri portal.

    Args:
        market: Market name (Yelahanka/Devanahalli/Hebbal). Case-insensitive.
        survey_no: Optional survey number to scope the check. When provided,
                   registration data is filtered to matching survey numbers.
        window_days: Lookback window for registration analysis (default 180).

    Returns:
        EncumbranceResult with avg GV PSF, registration count, avg txn PSF,
        guidance gap %, and risk flags. data_source indicates where the data
        was sourced from.
    """
    from utils.db import get_engine
    from sqlalchemy import text

    market = (market or "").strip()[:200]
    if not market:
        logger.warning("[Encumbrance] Empty market — returning unavailable")
        return EncumbranceResult(
            market="", survey_no=survey_no,
            avg_guidance_value_psf=None, registration_count_180d=0,
            avg_transaction_psf=None, guidance_gap_pct=None,
            data_source="unavailable",
            risk_flags=["Market name is empty"],
        )
    if survey_no:
        survey_no = survey_no.strip()[:100] or None

    risk_flags = []
    avg_gv = None
    reg_count = 0
    avg_txn_psf = None
    gap_pct = None
    data_source = "unavailable"

    try:
        with get_engine().connect() as conn:
            mm_row = conn.execute(
                text("SELECT id, name FROM micro_markets WHERE name ILIKE :name"),
                {"name": f"%{market}%"},
            ).fetchone()

            if not mm_row:
                logger.info("[Encumbrance] Market '%s' not found in DB — cannot check encumbrance", market)
                return EncumbranceResult(
                    market=market, survey_no=survey_no,
                    avg_guidance_value_psf=None, registration_count_180d=0,
                    avg_transaction_psf=None, guidance_gap_pct=None,
                    data_source="unavailable",
                    risk_flags=["Market not found in DB"],
                )

            mm_id, resolved_market = mm_row[0], mm_row[1]

            # Build survey number filter if provided
            survey_clause = ""
            survey_params: dict = {}
            if survey_no:
                survey_no_clean = survey_no.strip()
                if survey_no_clean:
                    survey_clause = " AND r.survey_number ILIKE :survey"
                    survey_params["survey"] = f"%{survey_no_clean}%"
                    logger.info("[Encumbrance] Filtering by survey_no=%s", survey_no_clean)

            # Get avg guidance value PSF for this market
            gv_row = conn.execute(text("""
                SELECT AVG(guidance_value_psf)::numeric
                FROM guidance_values
                WHERE micro_market_id = :mm_id AND guidance_value_psf > 0
            """), {"mm_id": mm_id}).scalar()
            avg_gv = float(gv_row) if gv_row else None

            # Registration count in configurable window
            cutoff = datetime.now() - timedelta(days=window_days)
            reg_count = conn.execute(text(f"""
                SELECT COUNT(*) FROM kaveri_registrations
                WHERE micro_market_id = :mm_id
                  AND transaction_date >= :cutoff
                  {survey_clause}
            """), {"mm_id": mm_id, "cutoff": cutoff.date(), **survey_params}).scalar() or 0

            # Avg transaction PSF (from area_sqft and transaction_amount)
            txn_row = conn.execute(text(f"""
                SELECT AVG(transaction_amount / NULLIF(area_sqft, 0))::numeric
                FROM kaveri_registrations
                WHERE micro_market_id = :mm_id
                  AND area_sqft > 0 AND transaction_amount > 0
                  AND transaction_date >= :cutoff
                  {survey_clause}
            """), {"mm_id": mm_id, "cutoff": cutoff.date(), **survey_params}).scalar()
            avg_txn_psf = float(txn_row) if txn_row else None

            if avg_gv is not None or avg_txn_psf is not None:
                data_source = "db"

    except Exception as exc:
        logger.warning("[Encumbrance] DB query failed for market=%s: %s", market, exc)
        return EncumbranceResult(
            market=market, survey_no=survey_no,
            avg_guidance_value_psf=None, registration_count_180d=0,
            avg_transaction_psf=None, guidance_gap_pct=None,
            data_source="unavailable",
            risk_flags=[f"DB query failed: {exc}"],
        )

    # Kaveri portal fallback — only when DB returned nothing for this market
    if avg_gv is None and avg_txn_psf is None:
        logger.info("[Encumbrance] DB has no data for market=%s — trying Kaveri portal fallback", market)
        portal_records = _fetch_from_kaveri_portal(market)
        if portal_records.get("guidance_values"):
            values = [r.get("guidance_value_psf", 0) for r in portal_records["guidance_values"] if r.get("guidance_value_psf", 0) > 0]
            if values:
                avg_gv = round(sum(values) / len(values), 1)
                data_source = "kaveri_portal"
        if portal_records.get("registrations"):
            psf_values = []
            for r in portal_records["registrations"]:
                area = r.get("area_sqft", 0)
                amt = r.get("transaction_amount", 0)
                if area > 0 and amt > 0:
                    psf_values.append(amt / area)
            if psf_values:
                avg_txn_psf = round(sum(psf_values) / len(psf_values), 1)
                reg_count = len(psf_values)
                data_source = "kaveri_portal"

    # Guidance gap %
    if avg_txn_psf and avg_gv and avg_gv > 0:
        gap_pct = round((avg_txn_psf - avg_gv) / avg_gv * 100, 1)

    # Risk flags
    if reg_count == 0:
        risk_flags.append(f"No registrations in {window_days}-day window — possible low liquidity or stale data")
    if avg_txn_psf is None:
        risk_flags.append("Unable to compute avg transaction PSF — sparse data")
    if gap_pct is not None and gap_pct > _GUIDANCE_GAP_THRESHOLD_PCT:
        risk_flags.append(f"Guidance gap {gap_pct}% exceeds {_GUIDANCE_GAP_THRESHOLD_PCT}% threshold — "
                          "price growth may significantly exceed circle rates")
    if survey_no and reg_count == 0:
        risk_flags.append(f"Survey no '{survey_no}' has no matching registrations — manual title search recommended")

    logger.info("[Encumbrance] market=%s survey=%s data_source=%s gv=%s regs=%d txn_psf=%s gap=%s%%",
                market, survey_no, data_source, avg_gv, reg_count, avg_txn_psf, gap_pct)

    return EncumbranceResult(
        market=market, survey_no=survey_no,
        avg_guidance_value_psf=avg_gv,
        registration_count_180d=reg_count,
        avg_transaction_psf=avg_txn_psf,
        guidance_gap_pct=gap_pct,
        data_source=data_source,
        risk_flags=risk_flags,
    )


def _fetch_from_kaveri_portal(market: str) -> dict:
    """Fallback: scrape Kaveri portal directly when DB has no data.

    Returns dict with optional 'guidance_values' and 'registrations' lists,
    or empty dict if portal is unreachable.
    """
    try:
        from scrapers.kaveri_karnataka import KaveriScraper
        scraper = KaveriScraper()
        gv = scraper.scrape_guidance_values(market)
        reg = scraper.scrape_registrations(market, months_back=6)
        logger.info("[Encumbrance] Kaveri portal returned gv=%d reg=%d for market=%s", len(gv), len(reg), market)
        result: dict = {}
        if gv:
            result["guidance_values"] = gv
        if reg:
            result["registrations"] = reg
        return result
    except Exception as exc:
        logger.warning("[Encumbrance] Kaveri portal fallback failed for market=%s: %s", market, exc)
        return {}


if __name__ == "__main__":
    import json
    for m in ("Yelahanka", "Devanahalli", "Hebbal", "Nonexistent"):
        result = check_encumbrance(m)
        print(f"\n[{m}]")
        print(json.dumps({k: v for k, v in result.__dict__.items()}, indent=2, default=str))
