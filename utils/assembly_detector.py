"""
RE_OS — Land Assembly Detector (GATE-92, T-1143)

Detects developers quietly assembling land parcels: same normalized buyer name
appearing on ≥2 registered_transactions in the same village within 180 days
where survey_no numeric prefixes are within ±3 of each other.

Writes to assembly_signals table and fires Discord alert to #competitor-launches.
"""

import re
from datetime import date, timedelta
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine

_ASSEMBLY_WINDOW_DAYS = 180
_FUZZY_THRESHOLD = 0.9
_PARCEL_PROXIMITY = 3


def _normalize_buyer(name: str) -> str:
    """Normalise buyer name for matching: uppercase, strip, collapse whitespace."""
    if not name:
        return ""
    return " ".join(name.strip().upper().split())


def _fuzzy_match(name_a: str, name_b: str, threshold: float = _FUZZY_THRESHOLD) -> bool:
    """Simple fuzzy match: exact, substring, or token-overlap.

    Returns True if names match above threshold. Uses string overlap for
    cases like 'BRIGADE GROUP' vs 'BRIGADE ENTERPRISES'.
    """
    if not name_a or not name_b:
        return False
    a = _normalize_buyer(name_a)
    b = _normalize_buyer(name_b)
    if a == b:
        return True
    if a in b or b in a:
        return True
    # Token overlap
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))
    return overlap >= threshold


def _parse_survey_prefix(survey_no: str) -> int | None:
    """Extract numeric prefix from survey number for proximity check. '45/2A' -> 45."""
    m = re.match(r"(\d+)", survey_no)
    return int(m.group(1)) if m else None


def _surveys_are_proximal(
    survey_nos: list[str], proximity: int = _PARCEL_PROXIMITY
) -> bool:
    """Check if survey number numeric prefixes span a contiguous range.

    Uses range-based check: max(prefix) - min(prefix) ≤ proximity.
    This correctly accepts ['45/1', '45/2', '48/3'] as proximal (48-45=3 ≤ 3)
    whereas the all-pairs check would reject 45/1 vs 48/3 (gap=3 which is equal,
    not exceeding; actual spec says within ±3 which includes the boundary).
    """
    prefixes = []
    for s in survey_nos:
        p = _parse_survey_prefix(s)
        if p is not None:
            prefixes.append(p)
    if len(prefixes) < 2:
        return False
    return (max(prefixes) - min(prefixes)) <= proximity


def detect_assemblies(markets: list[str] | None = None) -> list[dict]:
    """Scan registered_transactions for land assembly signals.

    Query: group by normalized buyer name in the same village within window_days,
    requiring ≥2 deeds with proximal survey numbers. Writes to assembly_signals table.
    """
    engine = get_engine()
    now = date.today()
    cutoff = now - timedelta(days=_ASSEMBLY_WINDOW_DAYS)
    signals = []

    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, buyer_name_raw, village, survey_no, reg_date,
                       extent_sqft, consideration_inr
                FROM registered_transactions
                WHERE buyer_name_raw IS NOT NULL AND buyer_name_raw != ''
                  AND survey_no IS NOT NULL AND survey_no != ''
                  AND village IS NOT NULL AND village != ''
                  AND reg_date >= :cutoff
                ORDER BY village, buyer_name_raw, reg_date
            """),
            {"cutoff": cutoff},
        ).fetchall()

    # Group by (village, normalized buyer)
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        norm = _normalize_buyer(row.buyer_name_raw)
        if not norm:
            continue
        key = (row.village, norm)
        if key not in groups:
            groups[key] = []
        groups[key].append(
            {
                "id": str(row.id),
                "buyer_name_raw": row.buyer_name_raw,
                "buyer_name_norm": norm,
                "village": row.village,
                "survey_no": row.survey_no,
                "reg_date": row.reg_date,
                "extent_sqft": float(row.extent_sqft) if row.extent_sqft else None,
                "consideration_inr": float(row.consideration_inr)
                if row.consideration_inr
                else None,
            }
        )

    # Second pass: merge groups within same village whose buyer names fuzzy-match
    # O(n²) but n = distinct buyer names per village, typically < 20
    merged_keys: set[tuple[str, str]] = set()
    fuzzy_merge_map: dict[tuple[str, str], tuple[str, str]] = {}
    village_groups: dict[str, list[tuple[str, str]]] = {}
    for (v, b), deeds in groups.items():
        if deeds:
            village_groups.setdefault(v, []).append((v, b))
    for v, key_list in village_groups.items():
        for i in range(len(key_list)):
            for j in range(i + 1, len(key_list)):
                k_a = key_list[i]
                k_b = key_list[j]
                if k_a in merged_keys or k_b in merged_keys:
                    continue
                name_a = k_a[1]
                name_b = k_b[1]
                if name_a != name_b and _fuzzy_match(
                    name_a, name_b, threshold=_FUZZY_THRESHOLD
                ):
                    # Merge smaller into larger
                    if len(groups[k_a]) >= len(groups[k_b]):
                        primary, secondary = k_a, k_b
                    else:
                        primary, secondary = k_b, k_a
                    fuzzy_merge_map[secondary] = primary

    for secondary, primary in fuzzy_merge_map.items():
        groups[primary].extend(groups[secondary])
        del groups[secondary]

    written = 0
    with engine.begin() as conn:
        for (village, norm_buyer), deeds in groups.items():
            if len(deeds) < 2:
                continue

            survey_nos = [d["survey_no"] for d in deeds]
            if not _surveys_are_proximal(survey_nos):
                continue

            total_extent = sum(d["extent_sqft"] for d in deeds if d["extent_sqft"])
            total_consideration = sum(
                d["consideration_inr"] for d in deeds if d["consideration_inr"]
            )
            first_date = min(d["reg_date"] for d in deeds)
            last_date = max(d["reg_date"] for d in deeds)
            days_span = (last_date - first_date).days if first_date and last_date else 0
            confidence = min(
                1.0, 0.5 + (len(deeds) - 2) * 0.15 + min(days_span, 180) / 180 * 0.2
            )

            existing = conn.execute(
                text("""
                    SELECT id, parcel_count FROM assembly_signals
                    WHERE buyer_name_norm = :b AND village = :v AND status = 'open'
                """),
                {"b": norm_buyer, "v": village},
            ).fetchone()

            if existing:
                conn.execute(
                    text("""
                        UPDATE assembly_signals
                        SET parcel_count = :cnt, total_extent_sqft = :ext,
                            total_consideration_inr = :cons,
                            first_deed_date = :fd, last_deed_date = :ld,
                            survey_nos = :sn, confidence = :conf,
                            updated_at = NOW()
                        WHERE id = :eid
                    """),
                    {
                        "cnt": len(deeds),
                        "ext": total_extent,
                        "cons": total_consideration,
                        "fd": first_date,
                        "ld": last_date,
                        "sn": survey_nos,
                        "conf": confidence,
                        "eid": existing[0],
                    },
                )
            else:
                conn.execute(
                    text("""
                        INSERT INTO assembly_signals
                            (buyer_name_norm, village, parcel_count, total_extent_sqft,
                             total_consideration_inr, first_deed_date, last_deed_date,
                             survey_nos, confidence, status)
                        VALUES (:b, :v, :cnt, :ext, :cons, :fd, :ld, :sn, :conf, 'open')
                        ON CONFLICT (buyer_name_norm, village)
                        DO UPDATE SET
                            parcel_count = EXCLUDED.parcel_count,
                            total_extent_sqft = EXCLUDED.total_extent_sqft,
                            total_consideration_inr = EXCLUDED.total_consideration_inr,
                            first_deed_date = EXCLUDED.first_deed_date,
                            last_deed_date = EXCLUDED.last_deed_date,
                            survey_nos = EXCLUDED.survey_nos,
                            confidence = EXCLUDED.confidence,
                            updated_at = NOW()
                    """),
                    {
                        "b": norm_buyer,
                        "v": village,
                        "cnt": len(deeds),
                        "ext": total_extent,
                        "cons": total_consideration,
                        "fd": first_date,
                        "ld": last_date,
                        "sn": survey_nos,
                        "conf": confidence,
                    },
                )
            written += 1

            raw_buyer = deeds[0]["buyer_name_raw"]
            signals.append(
                {
                    "buyer_name_norm": norm_buyer,
                    "buyer_name_raw": raw_buyer,
                    "village": village,
                    "parcel_count": len(deeds),
                    "total_extent_sqft": total_extent,
                    "total_consideration_inr": total_consideration,
                    "first_deed_date": str(first_date) if first_date else None,
                    "last_deed_date": str(last_date) if last_date else None,
                    "days_span": days_span,
                    "confidence": round(confidence, 3),
                    "survey_nos": survey_nos,
                }
            )

    # Write falsifiable claims to prediction_ledger (GATE-93, T-1148)
    try:
        from utils.prediction_ledger import write_prediction_ledger
        from datetime import timedelta as _td

        def _village_to_market(v: str) -> str:
            vl = v.lower()
            if "yelahanka" in vl:
                return "Yelahanka"
            if "devanahalli" in vl:
                return "Devanahalli"
            if "hebbal" in vl:
                return "Hebbal"
            return "unknown"

        for sig in signals:
            village = sig.get("village", "")
            write_prediction_ledger(
                source_module="assembly_detector",
                claim_type="assembly_alert",
                market=_village_to_market(village),
                claim_text=(
                    f"Land assembly: {sig['buyer_name_norm']} — "
                    f"{sig['parcel_count']} parcels in {sig['village']} "
                    f"over {sig['days_span']}d"
                ),
                falsifiable_metric=(
                    f"Developer {sig['buyer_name_norm']} confirms active "
                    f"land assembly in {sig['village']} with ≥{sig['parcel_count']} parcels"
                ),
                predicted_value=float(sig.get("total_consideration_inr", 0) or 0),
                check_date=date.today() + _td(days=365),
                confidence=float(sig.get("confidence", 0.5)),
            )
    except Exception:
        logger.debug("[AssemblyDetector] prediction_ledger write skipped (non-fatal)")

    logger.info(
        "[AssemblyDetector] {} assemblies detected, {} written to DB",
        len(signals),
        written,
    )
    return signals


def _format_assembly_alert(signal: dict) -> str:
    """Format an assembly signal into a Discord alert message."""
    extent_str = (
        f"{signal['total_extent_sqft']:,.0f} sqft"
        if signal.get("total_extent_sqft")
        else "unknown extent"
    )
    return (
        f"LAND ASSEMBLY: {signal['buyer_name_norm']} — "
        f"{signal['parcel_count']} parcels, {extent_str} "
        f"in {signal['village']} over {signal['days_span']}d"
    )


def run_assembly_detection():
    """Scheduler job: detect assemblies and fire Discord alerts.

    Runs after kaveri_deeds_weekly (Sunday ~03:15 IST).
    Dedup: only fires alert per signal once (discord_alerted flag).
    """
    logger.info("[AssemblyDetector] Scheduled run starting")
    try:
        signals = detect_assemblies()
        if not signals:
            logger.info("[AssemblyDetector] No assemblies detected")
            return

        from utils.discord_notifier import send

        engine = get_engine()

        for sig in signals:
            with engine.begin() as conn:
                row = conn.execute(
                    text("""
                        SELECT discord_alerted FROM assembly_signals
                        WHERE buyer_name_norm = :b AND village = :v
                    """),
                    {"b": sig["buyer_name_norm"], "v": sig["village"]},
                ).fetchone()
                if row and row[0]:
                    logger.debug(
                        "[AssemblyDetector] Dedup skip: {}/{}",
                        sig["buyer_name_norm"],
                        sig["village"],
                    )
                    continue

                alert = _format_assembly_alert(sig)
                try:
                    send(
                        "competitor-launches",
                        f"Land Assembly — {sig['buyer_name_norm']}",
                        alert,
                    )
                    conn.execute(
                        text(
                            "UPDATE assembly_signals SET discord_alerted = true WHERE buyer_name_norm = :b AND village = :v"
                        ),
                        {"b": sig["buyer_name_norm"], "v": sig["village"]},
                    )
                except Exception as exc:
                    logger.warning("[AssemblyDetector] Discord send failed: {}", exc)

        logger.info(
            "[AssemblyDetector] Scheduled run complete — {} assemblies alerted",
            len(signals),
        )
    except Exception as exc:
        logger.warning("[AssemblyDetector] Scheduled run failed: {}", exc)
