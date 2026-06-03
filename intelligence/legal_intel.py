"""
RE_OS — Legal Intelligence Module (Sprint 62)
LegalIntel.get_survey_picture(survey_no, market): 8-flag title risk checklist
evaluating encumbrance, regulatory zone, overlay constraints, RERA activity,
guidance gap, litigation risk, land use conversion need, and inheritance risk.

Returns LegalPicture with CLEAR/WARNING/RISK composite risk_level.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from loguru import logger

from intelligence._shared import (
    __all__ as _,
    fval, sanitize_market, sanitize_survey, validate_market,
    MarketCache, timed_intel_query,
)

__all__ = ["LegalIntel", "LegalPicture", "TitleRiskFlag"]


@dataclass
class TitleRiskFlag:
    flag: str
    status: str
    detail: str = ""
    severity: str = "low"

    def __str__(self) -> str:
        icon = {"CLEAR": "✓", "WARNING": "△", "RISK": "✗", "UNKNOWN": "?"}.get(self.status, "?")
        return f"{icon} [{self.severity.upper()}] {self.flag}: {self.detail}"


@dataclass
class LegalPicture:
    survey_no: str
    market: str
    collected_at: str
    market_found: bool = True

    encumbrance_registrations: int = 0
    encumbrance_last_transfer: str | None = None

    zone: str | None = None
    zone_risk_level: str = "UNKNOWN"
    overlay_count: int = 0
    overlay_risks: list[str] = field(default_factory=list)

    rera_projects_nearby: int = 0
    rera_avg_absorption: float | None = None

    guidance_value_psf: float | None = None
    guidance_market_gap_pct: float | None = None

    litigation_risk: str = "UNKNOWN"
    land_use_conversion_needed: str = "UNKNOWN"
    inheritance_risk: str = "UNKNOWN"

    title_risk_flags: list[TitleRiskFlag] = field(default_factory=list)
    risk_level: str = "UNKNOWN"

    def __str__(self) -> str:
        flag_summary = ", ".join(f"{f.flag}={f.status}" for f in self.title_risk_flags)
        return f"[LegalPicture:{self.market}/{self.survey_no}] {self.risk_level} | {flag_summary}"


class LegalIntel:
    """8-flag title risk assessment. Survey-level legal intelligence.

    Usage:
        pic = LegalIntel().get_survey_picture("45/2", "Yelahanka")
        print(pic.risk_level, pic.title_risk_flags)
    """

    def __init__(self, caller: str = ""):
        self._caller = caller or "LegalIntel"
        self._cache = MarketCache()

    def get_survey_picture(self, survey_no: str, market: str) -> LegalPicture:
        s = sanitize_survey(survey_no)
        m_raw = sanitize_market(market)
        if not s or not m_raw:
            return LegalPicture(
                survey_no=survey_no, market=m_raw or "",
                collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=bool(m_raw),
            )

        mi = validate_market(m_raw)
        if mi is None:
            return LegalPicture(
                survey_no=s, market=m_raw,
                collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=False,
            )

        pic = LegalPicture(
            survey_no=s, market=mi["name"],
            collected_at=datetime.now(timezone.utc).isoformat(),
            market_found=True,
        )

        try:
            from utils.db import get_engine
            from sqlalchemy import text
            engine = get_engine(pool_size=3, max_overflow=1)
            with engine.connect() as conn:
                self._check_encumbrance(conn, pic, s)
                self._check_zone_risk(conn, pic, mi)
                self._check_overlay_constraints(conn, pic, mi)
                self._check_nearby_rera(conn, pic, mi)
                self._check_guidance_value(conn, pic, mi)
                self._check_litigation(conn, pic, mi)
                self._check_land_use_conversion(conn, pic, mi)
                self._check_inheritance(conn, pic, mi)

            self._compute_risk_level(pic)

        except Exception as exc:
            logger.warning("[{}] get_survey_picture({}, {}) failed: {}",
                           self._caller, s, mi["name"], exc)
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="db_error", status="UNKNOWN",
                detail=f"DB query failed: {exc}", severity="high",
            ))

        return pic

    def _check_encumbrance(self, conn, pic: LegalPicture, survey: str):
        from sqlalchemy import text
        with timed_intel_query("legal_encumbrance"):
            rows = conn.execute(text("""
                SELECT transaction_amount, registration_date, buyer_name, seller_name
                FROM kaveri_registrations
                WHERE survey_number = :s
                ORDER BY registration_date DESC
                LIMIT 20
            """), {"s": survey}).fetchall()

        pic.encumbrance_registrations = len(rows)
        if rows:
            last = rows[0]
            pic.encumbrance_last_transfer = (
                f"{last[3]} → {last[2]} on {last[1]}" if last[1] else str(last[3])
            ) if len(last) >= 4 else str(last[0])

        if pic.encumbrance_registrations == 0:
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="encumbrance_history", status="WARNING",
                detail="No registrations found for survey — verify land records manually",
                severity="medium",
            ))
        elif pic.encumbrance_registrations >= 3:
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="encumbrance_history", status="CLEAR",
                detail=f"{pic.encumbrance_registrations} registrations on record, last: {pic.encumbrance_last_transfer}",
                severity="low",
            ))
        else:
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="encumbrance_history", status="WARNING",
                detail=f"Only {pic.encumbrance_registrations} registration(s) — limited chain of title",
                severity="medium",
            ))

    def _check_zone_risk(self, conn, pic: LegalPicture, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("legal_zone"):
            row = conn.execute(text("""
                SELECT zone_code, zone_description, far_base
                FROM regulatory_zones rz
                JOIN micro_markets mm ON mm.id = rz.micro_market_id
                WHERE mm.slug = :slug
                LIMIT 1
            """), {"slug": mi["slug"]}).fetchone()
        if row:
            pic.zone = str(row[0])
            pic.zone_risk_level = "LOW"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="regulatory_zone", status="CLEAR",
                detail=f"Zone {row[0]} — FAR {row[2]}, standard development controls apply",
                severity="low",
            ))
        else:
            pic.zone_risk_level = "RISK"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="regulatory_zone", status="RISK",
                detail="No regulatory zone data — verify land use classification manually",
                severity="high",
            ))

    def _check_overlay_constraints(self, conn, pic: LegalPicture, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("legal_overlay"):
            rows = conn.execute(text("""
                SELECT constraint_type, description
                FROM overlay_constraints
            """)).fetchall()
        pic.overlay_count = len(rows)
        pic.overlay_risks = []
        for r in rows:
            if r[0]:
                pic.overlay_risks.append(f"{r[0]}: {r[1]}" if r[1] else str(r[0]))
        if rows:
            detail = ", ".join(str(r[0]) for r in rows if r[0])
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="overlay_constraints",
                status="WARNING" if len(rows) <= 2 else "RISK",
                detail=f"{len(rows)} overlay(s) (city-wide scan): {detail}",
                severity="high" if len(rows) > 2 else "medium",
            ))

    def _check_nearby_rera(self, conn, pic: LegalPicture, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("legal_rera_activity"):
            row = conn.execute(text("""
                SELECT COUNT(*) AS total, ROUND(AVG(r.absorption_pct), 1) AS avg_abs
                FROM rera_projects r
                JOIN micro_markets mm ON mm.id = r.micro_market_id
                WHERE mm.slug = :slug AND r.is_active = TRUE
            """), {"slug": mi["slug"]}).fetchone()
        if row:
            pic.rera_projects_nearby = int(row[0]) if row[0] else 0
            pic.rera_avg_absorption = fval(row[1])
            status = "CLEAR" if pic.rera_projects_nearby >= 10 else "WARNING"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="market_rera_activity", status=status,
                detail=f"{pic.rera_projects_nearby} active RERA projects, avg absorption {pic.rera_avg_absorption}%",
                severity="low",
            ))

    def _check_guidance_value(self, conn, pic: LegalPicture, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("legal_guidance_value"):
            row = conn.execute(text("""
                SELECT AVG(kr.guidance_value) AS avg_gv, AVG(kr.guidance_market_gap_pct) AS avg_gap
                FROM kaveri_registrations kr
                JOIN micro_markets mm ON mm.id = kr.micro_market_id
                WHERE mm.slug = :slug
                  AND kr.guidance_value IS NOT NULL AND kr.guidance_value > 0
            """), {"slug": mi["slug"]}).fetchone()
        if row and row[0]:
            pic.guidance_value_psf = fval(row[0])
            pic.guidance_market_gap_pct = fval(row[1])
            gap = pic.guidance_market_gap_pct or 0
            status = "WARNING" if abs(gap) > 30 else "CLEAR"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="guidance_value_gap", status=status,
                detail=f"Guidance avg ₹{pic.guidance_value_psf:,.0f}/sqft, market gap {gap:+.1f}%",
                severity="medium",
            ))

    def _check_litigation(self, conn, pic: LegalPicture, mi: dict):
        """Flag 6: Check survey_no for litigation signals in news or agent_runs."""
        from sqlalchemy import text
        with timed_intel_query("legal_litigation"):
            row = conn.execute(text("""
                SELECT COUNT(*)
                FROM news_articles na
                JOIN micro_markets mm ON mm.id = na.micro_market_id
                WHERE mm.slug = :slug
                  AND (na.title ILIKE '%litigation%'
                       OR na.title ILIKE '%court%'
                       OR na.title ILIKE '%dispute%'
                       OR na.title ILIKE '%case filed%')
            """), {"slug": mi["slug"]}).fetchone()
        count = int(row[0]) if row and row[0] else 0
        if count > 0:
            pic.litigation_risk = "ALERT"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="litigation_risk", status="RISK",
                detail=f"{count} news articles mention litigation/court/dispute in this market",
                severity="high",
            ))
        else:
            pic.litigation_risk = "CLEAR"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="litigation_risk", status="CLEAR",
                detail="No litigation signals detected in recent news",
                severity="low",
            ))

    def _check_land_use_conversion(self, conn, pic: LegalPicture, mi: dict):
        """Flag 7: Check zone type for land-use conversion signal.
        Agricultural/non-urban zones may require conversion under KTCPA."""
        from sqlalchemy import text
        with timed_intel_query("legal_land_use"):
            row = conn.execute(text("""
                SELECT zone_type, zone_description
                FROM regulatory_zones rz
                JOIN micro_markets mm ON mm.id = rz.micro_market_id
                WHERE mm.slug = :slug
                LIMIT 1
            """), {"slug": mi["slug"]}).fetchone()
        if row:
            zone_type = str(row[0]) if row[0] else ""
            needs_conversion = any(
                kw in zone_type.lower()
                for kw in ("agriculture", "green", "rural", "industrial", "conservation")
            )
            if needs_conversion:
                pic.land_use_conversion_needed = "REQUIRED"
                pic.title_risk_flags.append(TitleRiskFlag(
                    flag="land_use_conversion", status="WARNING",
                    detail=f"Zone {row[0]} may require KTCPA land use conversion — BMRDA/BBMP approval needed",
                    severity="high",
                ))
            else:
                pic.land_use_conversion_needed = "NOT_REQUIRED"
                pic.title_risk_flags.append(TitleRiskFlag(
                    flag="land_use_conversion", status="CLEAR",
                    detail=f"Zone {row[0]} ({row[1]}) — compatible with residential development",
                    severity="low",
                ))
        else:
            pic.land_use_conversion_needed = "UNKNOWN"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="land_use_conversion", status="UNKNOWN",
                detail="Unable to determine zone — manual verification required",
                severity="high",
            ))

    def _check_inheritance(self, conn, pic: LegalPicture, mi: dict):
        """Flag 8: Check kaveri_registrations for multi-party transactions
        that may indicate inheritance/succession risk."""
        from sqlalchemy import text
        with timed_intel_query("legal_inheritance"):
            row = conn.execute(text("""
                SELECT COUNT(*) AS multi_party
                FROM kaveri_registrations kr
                JOIN micro_markets mm ON mm.id = kr.micro_market_id
                WHERE mm.slug = :slug
                  AND kr.seller_name IS NOT NULL
                  AND kr.seller_name LIKE '%&%'
            """), {"slug": mi["slug"]}).fetchone()
        count = int(row[0]) if row and row[0] else 0
        if count > 5:
            pic.inheritance_risk = "ALERT"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="inheritance_dispute_risk", status="RISK",
                detail=f"{count} multi-party seller transactions found — verify clear title",
                severity="high",
            ))
        elif count > 0:
            pic.inheritance_risk = "WATCH"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="inheritance_dispute_risk", status="WARNING",
                detail=f"{count} multi-party seller transactions — recommend title search",
                severity="medium",
            ))
        else:
            pic.inheritance_risk = "CLEAR"
            pic.title_risk_flags.append(TitleRiskFlag(
                flag="inheritance_dispute_risk", status="CLEAR",
                detail="No multi-party seller pattern detected",
                severity="low",
            ))

    def _compute_risk_level(self, pic: LegalPicture):
        risks = sum(1 for f in pic.title_risk_flags if f.status == "RISK")
        warnings = sum(1 for f in pic.title_risk_flags if f.status == "WARNING")
        unknowns = sum(1 for f in pic.title_risk_flags if f.status == "UNKNOWN")
        if risks > 0:
            pic.risk_level = "RISK"
        elif warnings > 2:
            pic.risk_level = "WARNING"
        elif unknowns > 0 and warnings == 0 and risks == 0:
            pic.risk_level = "INCOMPLETE"
        elif warnings == 0 and risks == 0:
            pic.risk_level = "CLEAR"
        else:
            pic.risk_level = "WARNING"


if __name__ == "__main__":
    import json
    pic = LegalIntel(caller="self_test").get_survey_picture("45/2", "Yelahanka")
    print(json.dumps({
        "survey_no": pic.survey_no,
        "market": pic.market,
        "market_found": pic.market_found,
        "risk_level": pic.risk_level,
        "flags": [str(f) for f in pic.title_risk_flags],
        "zone": pic.zone,
        "encumbrance": pic.encumbrance_registrations,
    }, indent=2, default=str))
