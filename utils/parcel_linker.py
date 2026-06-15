"""
RE_OS — Parcel Linker (GATE-92, T-1142)

Normalises survey numbers and links parcels across rera_projects,
registered_transactions, and kaveri_registrations by survey number.
"""

import re
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine


def normalize_survey_no(raw: str) -> str | None:
    """Normalize a survey number string to canonical form.

    Rules: uppercase, strip whitespace, unify separators.
    '45/2A', '45/2-A', '45/2 A', '45/2  A' → '45/2A'
    Returns None on garbage input (empty, all punctuation, too short).
    """
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip().upper()
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
