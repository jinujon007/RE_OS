"""
RE_OS — RERA Compliance Checker (Phase 12 — Legal Department)
Queries the DB for a developer's RERA project history and compliance signals.
Supports optional market scoping to distinguish track record per micro-market.
"""
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger


@dataclass
class RERAComplianceResult:
    developer_name: str
    market: str | None
    total_projects: int
    active_projects: int
    completed_projects: int
    delayed_projects: int
    avg_delay_months: float
    last_project_completed_at: str | None  # ISO date of most recently completed project
    months_since_last_project: float | None
    inactive_anomalies: list[dict]  # projects where is_active=False for investigation
    compliance_signal: str           # CLEAN | WATCH | RISK | UNKNOWN
    notes: list[str]


def check_developer_compliance(
    developer_name: str,
    market: str | None = None,
) -> RERAComplianceResult:
    """Query rera_projects + developers for this developer's track record.

    Args:
        developer_name: Developer name (case-insensitive, exact match preferred,
                        falls back to ILIKE %term%).
        market: Optional market slug to scope the check. When provided, only
                projects in that micro_market are counted.

    Returns:
        RERAComplianceResult with aggregate stats, inactive anomalies, and signal.
        Returns UNKNOWN signal with empty stats if developer not found or DB error.
    """
    from utils.db import get_engine
    from sqlalchemy import text

    developer_name = (developer_name or "").strip()[:500]
    if not developer_name:
        logger.warning("[RERACompliance] Empty developer_name — returning UNKNOWN")
        return RERAComplianceResult(
            developer_name="", market=market, total_projects=0, active_projects=0,
            completed_projects=0, delayed_projects=0, avg_delay_months=0.0,
            last_project_completed_at=None, months_since_last_project=None,
            inactive_anomalies=[], compliance_signal="UNKNOWN",
            notes=["Empty developer name provided"],
        )

    notes = []
    try:
        with get_engine().connect() as conn:
            # Step 1: Resolve developer_id — market-scoped exact match first, then market fuzzy, then global fallback
            dev_row = None
            if market:
                dev_row = conn.execute(
                    text("""
                        SELECT DISTINCT d.id, d.name FROM developers d
                        JOIN rera_projects r ON r.developer_id = d.id
                        JOIN micro_markets mm ON mm.id = r.micro_market_id
                        WHERE d.name ILIKE :exact AND mm.name ILIKE :market
                        LIMIT 1
                    """),
                    {"exact": developer_name, "market": f"%{market}%"},
                ).fetchone()
            if not dev_row:
                dev_row = conn.execute(
                    text("""
                        SELECT id, name FROM developers
                        WHERE name ILIKE :exact
                        LIMIT 1
                    """),
                    {"exact": developer_name},
                ).fetchone()
            if not dev_row:
                dev_row = conn.execute(
                    text("""
                        SELECT id, name FROM developers
                        WHERE name ILIKE :fuzzy
                        LIMIT 1
                    """),
                    {"fuzzy": f"%{developer_name}%"},
                ).fetchone()

            if not dev_row:
                return RERAComplianceResult(
                    developer_name=developer_name, market=market,
                    total_projects=0, active_projects=0, completed_projects=0,
                    delayed_projects=0, avg_delay_months=0.0,
                    last_project_completed_at=None, months_since_last_project=None,
                    inactive_anomalies=[], compliance_signal="UNKNOWN",
                    notes=["Developer not found in RERA Karnataka DB — verify name or check RERA portal directly"],
                )

            resolved_name = dev_row[1]
            if resolved_name.lower() != developer_name.lower():
                notes.append(f"Resolved '{developer_name}' → '{resolved_name}'")

            # Step 2: Build market filter
            market_clause = ""
            market_params: dict = {}
            if market:
                market_clause = " AND mm.name ILIKE :market"
                market_params["market"] = f"%{market}%"

            # Step 3: Aggregate compliance stats + recency
            row = conn.execute(text(f"""
                SELECT
                    COUNT(r.id) AS total,
                    COUNT(CASE WHEN r.is_active THEN 1 END) AS active,
                    COUNT(CASE WHEN r.project_status = 'Completed' THEN 1 END) AS completed,
                    COUNT(CASE WHEN r.delay_months > 0 THEN 1 END) AS delayed,
                    COALESCE(ROUND(AVG(r.delay_months)::numeric, 1), 0) AS avg_delay,
                    MAX(r.completion_date) AS last_completed,
                    MAX(r.created_at) AS last_activity
                FROM rera_projects r
                JOIN developers d ON d.id = r.developer_id
                LEFT JOIN micro_markets mm ON mm.id = r.micro_market_id
                WHERE d.id = :dev_id{market_clause}
            """), {"dev_id": dev_row[0], **market_params}).fetchone()

            # Step 4: Surface is_active=False anomalies
            anomalies = conn.execute(text(f"""
                SELECT r.project_name, r.rera_number, r.project_status,
                       r.delay_months, COALESCE(mm.name, 'unknown') AS market_name
                FROM rera_projects r
                LEFT JOIN micro_markets mm ON mm.id = r.micro_market_id
                WHERE r.developer_id = :dev_id
                  AND (r.is_active = FALSE OR r.project_status = 'Cancelled'
                       OR r.project_status = 'Suspended')
                  {("AND mm.name ILIKE :market") if market else ""}
                ORDER BY r.project_name
                LIMIT 20
            """), {"dev_id": dev_row[0], **market_params}).fetchall()

            inactive_anomalies = [
                {
                    "project": a[0],
                    "rera_number": a[1],
                    "status": a[2],
                    "delay_months": float(a[3]) if a[3] is not None else 0.0,
                    "market": a[4],
                }
                for a in anomalies
            ]
    except Exception as exc:
        logger.warning("[RERACompliance] DB query failed for developer=%s market=%s: %s",
                       developer_name, market, exc)
        return RERAComplianceResult(
            developer_name=developer_name, market=market,
            total_projects=0, active_projects=0, completed_projects=0,
            delayed_projects=0, avg_delay_months=0.0,
            last_project_completed_at=None, months_since_last_project=None,
            inactive_anomalies=[], compliance_signal="UNKNOWN",
            notes=["DB query failed — manual check required"],
        )

    total = int(row[0]) if row[0] else 0
    active = int(row[1]) if row[1] else 0
    completed = int(row[2]) if row[2] else 0
    delayed = int(row[3]) if row[3] else 0
    avg_delay = round(float(row[4]) if row[4] else 0.0, 1)
    last_completed_str = str(row[5]) if row[5] else None
    last_activity_str = str(row[6]) if row[6] else None

    # Compute months since last completed project
    months_since_last = None
    if last_completed_str:
        try:
            last_dt = datetime.fromisoformat(last_completed_str)
            months_since_last = round((datetime.now() - last_dt).days / 30.44, 1)
        except (ValueError, TypeError):
            pass

    if total == 0:
        return RERAComplianceResult(
            developer_name=resolved_name, market=market,
            total_projects=0, active_projects=0, completed_projects=0,
            delayed_projects=0, avg_delay_months=0.0,
            last_project_completed_at=None, months_since_last_project=None,
            inactive_anomalies=[], compliance_signal="UNKNOWN",
            notes=[f"Developer '{resolved_name}' found but has no projects in "
                   f"{'market ' + market if market else 'DB'}"],
        )

    if delayed == 0:
        signal = "CLEAN"
        notes.append(f"No delayed projects among {total} RERA-registered projects.")
    elif delayed / max(total, 1) < 0.3 and avg_delay < 6:
        signal = "WATCH"
        notes.append(f"{delayed}/{total} projects delayed, avg {avg_delay}mo — within tolerable range.")
    else:
        signal = "RISK"
        notes.append(f"{delayed}/{total} projects delayed, avg {avg_delay}mo — material delay risk.")

    if total < 3:
        notes.append("Fewer than 3 RERA projects — limited track record. Increase diligence.")

    if inactive_anomalies:
        notes.append(f"{len(inactive_anomalies)} project(s) with inactive/cancelled/suspended status — review details.")
    if months_since_last is not None and months_since_last > 36:
        notes.append(f"No completed projects in {months_since_last:.0f} months — verify developer is still active in this market.")

    market_tag = f" (market: {market})" if market else ""
    logger.info("[RERACompliance] developer=%s%s total=%d active=%d delayed=%d signal=%s anomalies=%d last_completed=%s",
                resolved_name, market_tag, total, active, delayed, signal, len(inactive_anomalies),
                last_completed_str or "none")

    return RERAComplianceResult(
        developer_name=resolved_name,
        market=market,
        total_projects=total,
        active_projects=active,
        completed_projects=completed,
        delayed_projects=delayed,
        avg_delay_months=avg_delay,
        last_project_completed_at=last_completed_str,
        months_since_last_project=months_since_last,
        inactive_anomalies=inactive_anomalies,
        compliance_signal=signal,
        notes=notes,
    )


if __name__ == "__main__":
    import json
    for name in ("Brigade", "Prestige", "NonexistentDeveloper"):
        result = check_developer_compliance(name)
        print(f"\n[{name}]")
        print(json.dumps({k: v for k, v in result.__dict__.items() if k != "inactive_anomalies"}, indent=2, default=str))
        if result.inactive_anomalies:
            print(f"  anomalies: {json.dumps(result.inactive_anomalies, indent=4)}")
