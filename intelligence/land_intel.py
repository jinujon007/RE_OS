"""
RE_OS — Land Intelligence Module (Sprint 62)
LandIntel.get_land_picture(survey_no, market): evaluates a specific land parcel
for development potential — zone, FSI, green coverage, overlay constraints,
infrastructure proximity, and development readiness assessment.

Returns LandPicture with development_readiness, flags, and estimated land value.
Gracefully degrades on missing data — never raises.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from loguru import logger

from intelligence._shared import (
    __all__ as _,
    fval, sanitize_market, sanitize_survey, validate_market, MarketCache, timed_intel_query,
)

__all__ = ["LandIntel", "LandPicture", "InfrastructureProximity"]


@dataclass
class InfrastructureProximity:
    infra_projects_nearby: int = 0
    upcoming_infra: list[str] = field(default_factory=list)
    has_metro_proximity: bool = False
    has_highway_proximity: bool = False
    accessibility_score: float = 0.0

    def __str__(self) -> str:
        return (
            f"{self.infra_projects_nearby} projects"
            f"{' (metro)' if self.has_metro_proximity else ''}"
            f"{' (highway)' if self.has_highway_proximity else ''}"
            f" acc={self.accessibility_score:.2f}"
        )


@dataclass
class LandPicture:
    survey_no: str
    market: str
    collected_at: str
    market_found: bool = True

    land_area_sqft: float | None = None
    land_area_acres: float | None = None
    zone: str | None = None
    current_use: str = "unknown"

    far: float | None = None
    buildable_area_sqft: float | None = None
    sellable_area_sqft: float | None = None
    max_floors: int = 0
    plot_coverage: float | None = None
    setback_front_m: float | None = None
    setback_side_m: float | None = None

    green_pct: float | None = None
    tree_count: int = 0
    meets_bda_minimum: bool = False

    overlay_count: int = 0
    overlay_risks: list[str] = field(default_factory=list)

    infrastructure: InfrastructureProximity | None = None

    estimated_land_value: float | None = None
    guidance_value_psf: float | None = None

    flood_risk: str = "UNKNOWN"
    topography: str = "UNKNOWN"
    development_readiness: str = "UNKNOWN"

    flags: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        area = f"{self.land_area_acres:.2f}ac" if self.land_area_acres else "N/A"
        return (
            f"[LandPicture:{self.market}/{self.survey_no}] "
            f"{area} | Zone {self.zone} | "
            f"FAR {self.far} | {self.development_readiness}"
        )


_ACRE_SQFT: float = 43560.0


class LandIntel:
    """Land parcel evaluation. Zone + FSI + constraints + infrastructure.

    Usage:
        pic = LandIntel().get_land_picture("45/2", "Yelahanka")
        print(pic.development_readiness, pic.flags)
    """

    def __init__(self, caller: str = ""):
        self._cache = MarketCache()
        self._caller = caller or "LandIntel"

    def get_land_picture(self, survey_no: str, market: str) -> LandPicture:
        s = sanitize_survey(survey_no)
        m_raw = sanitize_market(market)
        if not s or not m_raw:
            return LandPicture(
                survey_no=s or survey_no, market=m_raw or market,
                collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=bool(m_raw),
            )

        mi = validate_market(m_raw)
        if mi is None:
            return LandPicture(
                survey_no=s, market=m_raw,
                collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=False,
            )

        pic = LandPicture(
            survey_no=s, market=mi["name"],
            collected_at=datetime.now(timezone.utc).isoformat(),
            market_found=True,
        )

        try:
            from utils.db import get_engine
            from sqlalchemy import text
            engine = get_engine(pool_size=3, max_overflow=1)
            with engine.connect() as conn:
                self._load_survey_area(conn, pic, s, mi)
                self._load_regulatory_data(conn, pic, mi)
                self._load_overlay_data(conn, pic, mi)
                self._load_infrastructure(conn, pic, mi)
                self._load_guidance_value(conn, pic, mi)

            self._compute_development_metrics(pic)
            self._assess_risks(pic)

        except Exception as exc:
            logger.warning("[{}] get_land_picture({}, {}) failed: {}",
                           self._caller, s, mi["name"], exc)
            pic.flags.append(f"Query error: {exc}")

        return pic

    def _load_survey_area(self, conn, pic: LandPicture, survey: str, mi: dict):
        """Query kaveri_registrations and igr_transactions for actual land area."""
        from sqlalchemy import text
        with timed_intel_query("land_survey_area"):
            row = conn.execute(text("""
                SELECT AVG(area_sqft) AS avg_area
                FROM (
                    SELECT area_sqft FROM kaveri_registrations
                    WHERE survey_number ILIKE :s AND micro_market_id IN (
                        SELECT id FROM micro_markets WHERE slug = :slug
                    ) AND area_sqft IS NOT NULL AND area_sqft > 0
                    ORDER BY registration_date DESC LIMIT 5
                ) sub
            """), {"s": f"{survey}%", "slug": mi["slug"]}).fetchone()

            if not row or not row[0]:
                row = conn.execute(text("""
                    SELECT AVG(area_sqft) FROM igr_transactions
                    WHERE survey_no ILIKE :s AND micro_market_id IN (
                        SELECT id FROM micro_markets WHERE slug = :slug
                    ) AND area_sqft IS NOT NULL AND area_sqft > 0
                    LIMIT 5
                """), {"s": f"{survey}%", "slug": mi["slug"]}).fetchone()

        if row and row[0]:
            area = float(row[0])
            pic.land_area_sqft = round(area, 1)
            pic.land_area_acres = round(area / _ACRE_SQFT, 4)

    def _load_regulatory_data(self, conn, pic: LandPicture, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("land_regulatory"):
            row = conn.execute(text("""
                SELECT zone_code, far_base, max_height_m, ground_coverage_pct,
                       front_setback_m, side_setback_m, zone_description
                FROM regulatory_zones
                WHERE zone_code IS NOT NULL
                ORDER BY zone_type NULLS LAST, authority NULLS LAST
                LIMIT 1
            """)).fetchone()
        if row and row[0]:
            logger.info("[{}] Using regulatory zone {} for {} (no market FK in v1 schema)",
                        self._caller, row[0], mi.get("name", "?"))
        if row:
            pic.zone = str(row[0]) if row[0] else None
            pic.far = fval(row[1])
            pic.max_floors = int(float(row[2])) if row[2] else 0
            pic.plot_coverage = fval(row[3])
            pic.setback_front_m = fval(row[4])
            pic.setback_side_m = fval(row[5])
            pic.current_use = str(row[6]) if row[6] else "unknown"

    def _load_overlay_data(self, conn, pic: LandPicture, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("land_overlay"):
            rows = conn.execute(text("""
                SELECT constraint_type, description
                FROM overlay_constraints
            """)).fetchall()
        pic.overlay_risks = []
        for r in rows:
            if r[0]:
                pic.overlay_risks.append(f"{r[0]}: {r[1]}" if r[1] else str(r[0]))
        pic.overlay_count = len(pic.overlay_risks)

        flood_flags = [r for r in rows if r[0] and "lake" in str(r[0]).lower()]
        if flood_flags:
            pic.flood_risk = "ALERT"
        elif pic.overlay_count > 0:
            pic.flood_risk = "WATCH"

    def _load_infrastructure(self, conn, pic: LandPicture, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("land_infrastructure"):
            rows = conn.execute(text("""
                SELECT name, infra_type, project_status
                FROM infrastructure_pipeline
                ORDER BY expected_completion NULLS LAST
            """)).fetchall()
        infra = InfrastructureProximity()
        infra.infra_projects_nearby = len(rows)
        for r in rows:
            name = str(r[0]) if r[0] else ""
            itype = str(r[1]) if r[1] else ""
            status = str(r[2]) if r[2] else ""
            if itype == "Metro":
                infra.has_metro_proximity = True
            if itype in ("Road", "Expressway"):
                infra.has_highway_proximity = True
            if status and status not in ("Completed",):
                infra.upcoming_infra.append(f"{name} ({itype}, {status})")
        try:
            from scrapers.mobility_scout import compute_market_accessibility
            infra.accessibility_score = compute_market_accessibility(mi["name"], conn=conn)
        except Exception as exc:
            logger.warning("[{}] accessibility_score compute failed for {}: {}", self._caller, mi.get("name", "?"), exc)
        pic.infrastructure = infra

    def _load_guidance_value(self, conn, pic: LandPicture, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("land_guidance"):
            row = conn.execute(text("""
                SELECT AVG(guidance_value_psf) AS avg_gv
                FROM guidance_values gv
                JOIN micro_markets mm ON mm.id = gv.micro_market_id
                WHERE mm.slug = :slug
            """), {"slug": mi["slug"]}).fetchone()
        if row and row[0]:
            pic.guidance_value_psf = fval(row[0])

    def _compute_development_metrics(self, pic: LandPicture):
        try:
            area = pic.land_area_sqft or _ACRE_SQFT
            if pic.far and pic.plot_coverage:
                buildable = area * pic.far
                pic.buildable_area_sqft = round(buildable, 1)
                pic.sellable_area_sqft = round(buildable * 0.65, 1)
                pic.max_floors = max(
                    1, int(buildable / max(area * pic.plot_coverage, 1))
                )
                landscape = area * (1.0 - pic.plot_coverage)
                green_pct = (landscape / max(area, 1)) * 100
                pic.green_pct = round(green_pct, 1)
                pic.tree_count = max(1, int(landscape / 200))
                pic.meets_bda_minimum = green_pct >= 15.0

            if pic.guidance_value_psf:
                pic.estimated_land_value = round(area * pic.guidance_value_psf)

        except Exception as exc:
            logger.warning("[{}] _compute_development_metrics: {}", self._caller, exc)

    def _assess_risks(self, pic: LandPicture):
        if pic.overlay_count > 2:
            pic.development_readiness = "CONSTRAINED"
            pic.flags.append(f"{pic.overlay_count} overlay constraints — detailed survey needed")
        elif pic.overlay_count > 0:
            pic.development_readiness = "PARTIAL"
            pic.flags.append(f"{pic.overlay_count} overlay constraint(s) — verify exact buffer impact")
        elif pic.far:
            pic.development_readiness = "READY"

        if pic.meets_bda_minimum and pic.green_pct:
            pic.flags.append(f"BDA green coverage minimum met ({pic.green_pct:.0f}% ≥ 15%)")
        elif pic.green_pct is not None:
            pic.flags.append(f"Below BDA 15% green minimum ({pic.green_pct:.0f}%) — adjust site plan")
            if pic.development_readiness not in ("CONSTRAINED", "UNKNOWN"):
                pic.development_readiness = "PARTIAL"

        if not pic.far:
            pic.flags.append("No FAR data — manual BDA/BMRDA zone verification required")
            pic.development_readiness = "UNKNOWN"

        if pic.flood_risk == "ALERT":
            pic.flags.append("Lake buffer zone detected — flood risk, construction restrictions apply")
            pic.development_readiness = "CONSTRAINED"

        if pic.infrastructure:
            acc = getattr(pic.infrastructure, "accessibility_score", 0.0) or 0.0
            if acc < 0.3:
                pic.flags.append(f"Low transit accessibility (score={acc:.2f}) — may limit demand pool")
            elif acc < 0.5:
                pic.flags.append(f"Moderate transit accessibility (score={acc:.2f}) — monitor infra pipeline")


if __name__ == "__main__":
    import json
    pic = LandIntel(caller="self_test").get_land_picture("45/2", "Yelahanka")
    print(json.dumps({
        "survey_no": pic.survey_no,
        "market": pic.market,
        "market_found": pic.market_found,
        "land_area_acres": pic.land_area_acres,
        "zone": pic.zone,
        "far": pic.far,
        "buildable": pic.buildable_area_sqft,
        "green_pct": pic.green_pct,
        "readiness": pic.development_readiness,
        "flags": pic.flags,
    }, indent=2, default=str))
