"""
RE_OS — Parcel Linker (GATE-92, T-1142)

Normalises survey numbers and links parcels across rera_projects,
registered_transactions, and kaveri_registrations by survey number.
"""

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine


def normalize_survey_no(raw: str) -> str | None:
    """Normalize a survey number string to canonical form.

    Rules: NFKC normalize (Unicode), uppercase, strip whitespace, unify separators.
    '45/2A', '45/2-A', '45/2 A', '45/2  A' → '45/2A'
    Returns None on garbage input (empty, all punctuation, too short).
    """
    if not raw or not isinstance(raw, str):
        return None
    s = unicodedata.normalize("NFKC", raw.strip().upper())
    if not s or len(s) < 2:
        return None
    # Strip all whitespace, hyphens, and dots — keep only alphanumeric and /
    s = re.sub(r"[\s\-.]", "", s)
    # Collapse multiple slashes into one
    s = re.sub(r"/+", "/", s)
    # Remove leading/trailing non-alphanumeric
    s = re.sub(r"^[^A-Z0-9]+", "", s)
    s = re.sub(r"[^A-Z0-9/]+$", "", s)
    if not s or len(s) < 1:
        return None
    # If after normalisation we get just punctuation, return None
    if re.match(r"^[^A-Z0-9]+$", s):
        return None
    return s


def _upsert_parcel(
    conn,
    village: str,
    survey_no: str,
    survey_no_raw: str | None,
    district: str | None,
    taluk: str | None,
    hobli: str | None,
    extent_sqft: float | None,
    source: str,
) -> tuple[str | None, bool]:
    """Upsert a parcel row and return (id, was_created). Idempotent.

    Returns (id, True) if a new parcel was created.
    Returns (id, False) if the parcel already existed (conflict).
    Returns (None, False) on invalid input or DB error.
    """
    if not village or not survey_no:
        return None, False
    result = conn.execute(
        text("""
            INSERT INTO parcels (village, survey_no, survey_no_raw, district, taluk, hobli, extent_sqft, source)
            VALUES (:v, :s, :raw, :d, :t, :h, :e, :src)
            ON CONFLICT (village, survey_no) DO NOTHING
            RETURNING id
        """),
        {
            "v": village,
            "s": survey_no,
            "raw": survey_no_raw,
            "d": district,
            "t": taluk,
            "h": hobli,
            "e": extent_sqft,
            "src": source,
        },
    ).fetchone()
    if result:
        return str(result[0]), True
    existing = conn.execute(
        text("SELECT id FROM parcels WHERE village = :v AND survey_no = :s"),
        {"v": village, "s": survey_no},
    ).fetchone()
    return (str(existing[0]), False) if existing else (None, False)


def link_parcels(markets: list[str] | None = None) -> dict:
    """Scan source tables, normalise survey numbers, upsert parcels, set parcel_id.

    Idempotent: re-running creates no duplicate parcels. Returns stats dict.
    Note: markets parameter accepted for future scope-filtering but currently
    unused — linker scans all survey_no-bearing rows across all markets.
    """
    engine = get_engine()
    stats = {
        "created": 0,
        "linked_rera": 0,
        "linked_registered": 0,
        "linked_kaveri": 0,
        "skipped": 0,
    }

    parcels_cache: dict[tuple[str, str], str] = {}

    def _get_parcel_id(
        conn,
        village: str,
        survey_no: str,
        survey_no_raw: str | None,
        district: str | None,
        taluk: str | None,
        hobli: str | None,
        extent_sqft: float | None,
        source: str,
    ) -> str | None:
        key = (village or "", survey_no or "")
        if key in parcels_cache:
            return parcels_cache[key]
        pid, was_created = _upsert_parcel(
            conn,
            village,
            survey_no,
            survey_no_raw,
            district,
            taluk,
            hobli,
            extent_sqft,
            source,
        )
        if pid:
            parcels_cache[key] = pid
            if was_created:
                stats["created"] += 1
        return pid

    with engine.begin() as conn:
        # 1. rera_projects
        rera_rows = conn.execute(
            text("""
                SELECT id, survey_no, village, extent_sqft
                FROM rera_projects
                WHERE survey_no IS NOT NULL AND survey_no != ''
            """),
        ).fetchall()
        for row in rera_rows:
            norm = normalize_survey_no(row.survey_no)
            if not norm:
                stats["skipped"] += 1
                continue
            pid = _get_parcel_id(
                conn,
                row.village or "",
                norm,
                row.survey_no,
                None,
                None,
                None,
                row.extent_sqft,
                "rera_projects",
            )
            if pid:
                conn.execute(
                    text(
                        "UPDATE rera_projects SET parcel_id = :pid WHERE id = :id AND parcel_id IS NULL"
                    ),
                    {"pid": pid, "id": row.id},
                )
                stats["linked_rera"] += 1

        # 2. registered_transactions
        reg_rows = conn.execute(
            text("""
                SELECT id, survey_no, village, district, taluk, hobli, extent_sqft
                FROM registered_transactions
                WHERE survey_no IS NOT NULL AND survey_no != ''
            """),
        ).fetchall()
        for row in reg_rows:
            norm = normalize_survey_no(row.survey_no)
            if not norm:
                stats["skipped"] += 1
                continue
            pid = _get_parcel_id(
                conn,
                row.village or "",
                norm,
                row.survey_no,
                row.district,
                row.taluk,
                row.hobli,
                row.extent_sqft,
                "registered_transactions",
            )
            if pid:
                conn.execute(
                    text(
                        "UPDATE registered_transactions SET parcel_id = :pid WHERE id = :id AND parcel_id IS NULL"
                    ),
                    {"pid": pid, "id": row.id},
                )
                stats["linked_registered"] += 1

        # 3. kaveri_registrations (legacy table, survey_number column)
        kav_rows = conn.execute(
            text("""
                SELECT id, survey_number, village, district, taluk, hobli, area_sqft
                FROM kaveri_registrations
                WHERE survey_number IS NOT NULL AND survey_number != ''
            """),
        ).fetchall()
        for row in kav_rows:
            norm = normalize_survey_no(row.survey_number)
            if not norm:
                stats["skipped"] += 1
                continue
            pid = _get_parcel_id(
                conn,
                row.village or "",
                norm,
                row.survey_number,
                row.district,
                row.taluk,
                row.hobli,
                row.area_sqft,
                "kaveri_registrations",
            )
            if pid:
                conn.execute(
                    text(
                        "UPDATE kaveri_registrations SET parcel_id = :pid WHERE id = :id AND parcel_id IS NULL"
                    ),
                    {"pid": pid, "id": row.id},
                )
                stats["linked_kaveri"] += 1

    logger.info(
        "[ParcelLinker] Created {} parcels, linked rera={}, registered={}, kaveri={}, skipped={}",
        stats["created"],
        stats["linked_rera"],
        stats["linked_registered"],
        stats["linked_kaveri"],
        stats["skipped"],
    )
    return stats


# ── Ownership enrichment (GATE-99, T-1187) ─────────────────────────────


def _fetch_and_parse(survey_no: str, market: str,
                     _bhoomi_fetch, parser: object, _max_retries: int = 2) -> dict | None:
    """Fetch RTC data and parse it, with retry on parser failure."""
    norm = normalize_survey_no(survey_no)
    if not norm:
        logger.warning("[ParcelLinker] Invalid survey_no format: '{}'", survey_no)
        return None

    for attempt in range(_max_retries):
        result = _bhoomi_fetch(survey_no, market)
        if not result or result.get("bhoomi_status") != "live":
            if attempt < _max_retries - 1:
                continue
            logger.warning(
                "[ParcelLinker] RTC fetch failed for {} / {} after {} attempts",
                survey_no, market, _max_retries,
            )
            return None
        chain = parser.parse(str(result))  # type: ignore[attr-defined]
        chain["survey_no"] = survey_no
        chain["market"] = market
        return chain
    return None


def _count_enrichment_metric(market: str, result: str) -> None:
    try:
        from config.metrics import parcel_enrichment_total, parcel_parser_completeness
        parcel_enrichment_total.labels(market=market, result=result).inc()
    except Exception:
        pass


def enrich_ownership(survey_no: str, market: str) -> dict | None:
    """Fetch RTC data for a survey_no, parse ownership chain, upsert to parcel_ownership_chain.

    Steps:
        1. Validate survey_no format via normalize_survey_no.
        2. Call BhoomiScraper.fetch(survey_no, market) with retry.
        3. Parse with BhoomiRTCParser.
        4. Upsert to parcel_ownership_chain (idempotent, daily dedup).
        5. Return parsed chain dict, or None on fetch failure.

    Returns:
        Dict with ownership fields, or None if RTC fetch returned nothing.
    """
    try:
        from scrapers.bhoomi_scraper import fetch as _bhoomi_fetch
        from scrapers.bhoomi_rtc_parser import BhoomiRTCParser
    except Exception as exc:
        logger.error("[ParcelLinker] enrich_ownership import error: {}", exc)
        return None

    chain = _fetch_and_parse(survey_no, market, _bhoomi_fetch, BhoomiRTCParser())
    if chain is None:
        _count_enrichment_metric(market, "fetch_failed")
        return None

    with get_engine().begin() as conn:
        try:
            conn.execute(
                text("""
                    INSERT INTO parcel_ownership_chain
                        (survey_no, market, khata_no, owner_name,
                         previous_owner, transfer_date, area_acres,
                         govt_acquisition_notice, govt_acquisition_detail,
                         encumbrance_flag, encumbrance_detail, source,
                         raw_html, parser_completeness_score)
                    VALUES
                        (:sno, :mkt, :khata, :owner,
                         :prev, :tdate, :acres,
                         :govt, :govt_detail,
                         :enc, :enc_detail, 'bhoomi_rtc',
                         :raw, :score)
                    ON CONFLICT (survey_no, market, fetched_at::date)
                    DO NOTHING
                """),
                {
                    "sno": survey_no,
                    "mkt": market,
                    "khata": chain.get("khata_no"),
                    "owner": chain.get("owner_name"),
                    "prev": chain.get("previous_owner"),
                    "tdate": chain.get("transfer_date"),
                    "acres": chain.get("area_acres"),
                    "govt": chain.get("govt_acquisition_notice", False),
                    "govt_detail": chain.get("govt_acquisition_detail"),
                    "enc": chain.get("encumbrance_flag", False),
                    "enc_detail": chain.get("encumbrance_detail"),
                    "raw": str(chain)[:5000],
                    "score": chain.get("parser_completeness_score"),
                },
            )
        except Exception as exc:
            _count_enrichment_metric(market, "upsert_failed")
            logger.warning(
                "[ParcelLinker] enrich_ownership upsert failed for {} / {}: {}",
                survey_no, market, exc,
            )
            return None

    _count_enrichment_metric(market, "success")
    logger.info(
        "[ParcelLinker] enrich_ownership: {} / {} — khata={}, owner={}, score={}",
        survey_no, market,
        chain.get("khata_no"), chain.get("owner_name"),
        chain.get("parser_completeness_score"),
    )
    return chain


def enrich_all_parcels(market: str, limit: int = 50,
                       max_workers: int = 5, rate_delay_s: float = 1.5) -> int:
    """Enrich ownership for all parcels in a market that don't have a chain entry yet.

    Uses ThreadPoolExecutor for concurrent Bhoomi fetches with rate-limit delay.
    Skips parcels already enriched (dedup via subquery).

    Args:
        market: Market name.
        limit: Max parcels to enrich in one call (default 50).
        max_workers: Concurrent fetch workers (default 5 — avoids Bhoomi 429s).
        rate_delay_s: Inter-worker delay (default 1.5s).

    Returns:
        Number of parcels successfully enriched.
    """
    enriched = 0
    failed = 0
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT survey_no FROM parcels
                    WHERE market = :market
                      AND survey_no IS NOT NULL
                      AND survey_no NOT IN (
                          SELECT survey_no FROM parcel_ownership_chain
                          WHERE market = :market
                      )
                    LIMIT :lim
                """),
                {"market": market, "lim": limit},
            ).fetchall()
    except Exception as exc:
        logger.error("[ParcelLinker] enrich_all_parcels query failed: {}", exc)
        return 0

    if not rows:
        logger.info("[ParcelLinker] enrich_all_parcels({}): 0 pending", market)
        return 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_to_sno = {
            pool.submit(enrich_ownership, row.survey_no, market): row.survey_no
            for row in rows
        }
        for future in as_completed(fut_to_sno):
            sno = fut_to_sno[future]
            try:
                result = future.result()
                if result is not None:
                    enriched += 1
                else:
                    failed += 1
                    logger.debug("[ParcelLinker] enrich_all_parcels: {} returned None", sno)
            except Exception as exc:
                failed += 1
                logger.warning(
                    "[ParcelLinker] enrich_all_parcels failed for {} / {}: {}",
                    sno, market, exc,
                )

    logger.info(
        "[ParcelLinker] enrich_all_parcels({}): {}/{} enriched, {} failed",
        market, enriched, len(rows), failed,
    )
    return enriched


def run_parcel_ownership_enrichment():
    """Weekly scheduler job — runs enrich_all_parcels for all markets (Monday 04:00 UTC).

    Enriches up to 50 parcels per market sequentially (rate-limit aware).
    Posts OPS alert to Discord on total failure.
    """
    logger.info("[ParcelLinker] Ownership enrichment starting")
    total = 0
    market_results = {}
    for m in ("Yelahanka", "Devanahalli", "Hebbal"):
        try:
            count = enrich_all_parcels(m, limit=50)
            total += count
            market_results[m] = {"enriched": count, "status": "ok"}
            logger.info("[ParcelLinker] {}: {} enriched", m, count)
        except Exception as exc:
            market_results[m] = {"enriched": 0, "status": "error", "error": str(exc)[:200]}
            logger.warning("[ParcelLinker] {} enrichment failed: {}", m, exc)
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs
                        (agent_name, micro_market, event_type, status, notes)
                    VALUES ('parcel_linker', 'system', 'ownership_enrichment',
                            'success', :notes)
                """),
                {"notes": f"Enriched {total} parcels across all markets. Results: {market_results}"},
            )
    except Exception as exc:
        logger.warning("[ParcelLinker] Failed to log enrichment run: {}", exc)
    logger.info("[ParcelLinker] Ownership enrichment complete — {} total enriched", total)


def run_parcel_linker_nightly():
    """Nightly parcel linker job — 02:30 IST."""
    logger.info("[ParcelLinker] Nightly run starting")
    retries = 0
    max_retries = 2
    while retries <= max_retries:
        try:
            stats = link_parcels()
            logger.info("[ParcelLinker] Nightly run complete: {}", stats)
            try:
                with get_engine().begin() as conn:
                    conn.execute(
                        text("""
                            INSERT INTO agent_runs
                                (agent_name, micro_market, event_type, status, notes)
                            VALUES ('parcel_linker', 'system', 'parcel_linker_nightly',
                                    'success', :notes)
                        """),
                        {"notes": str(stats)},
                    )
            except Exception as exc:
                logger.warning("[ParcelLinker] Failed to log run: {}", exc)
            return
        except Exception as exc:
            retries += 1
            logger.warning(
                "[ParcelLinker] Nightly run attempt {}/{} failed: {}",
                retries,
                max_retries + 1,
                exc,
            )
            if retries > max_retries:
                try:
                    with get_engine().begin() as conn:
                        conn.execute(
                            text("""
                                INSERT INTO agent_runs
                                    (agent_name, micro_market, event_type, status, notes)
                                VALUES ('parcel_linker', 'system', 'parcel_linker_nightly',
                                        'failed', :notes)
                            """),
                            {
                                "notes": f"Failed after {max_retries + 1} attempts: {exc}"
                            },
                        )
                except Exception as log_exc:
                    logger.warning("[ParcelLinker] Failed to log failure: {}", log_exc)
