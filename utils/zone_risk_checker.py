"""
RE_OS — Zone Risk Checker (Phase 12 — Legal Department)
Queries regulatory_zones + overlay_constraints for a market/zone combination.
Returns FAR, setbacks, height limit, and any overlay risk flags.

Schema notes (from seed_regulatory_zones.sql):
  regulatory_zones.zone_type       → stores market name (Yelahanka/Devanahalli/Hebbal)
  regulatory_zones.far_base        → FAR value (not 'far')
  regulatory_zones.ground_coverage_pct → stored as percentage (55 = 55%, not 0.55)
  regulatory_zones.front_setback_m → front setback (not 'setback_front_m')
  regulatory_zones.side_setback_m  → side setback (not 'setback_side_m')
  overlay_constraints              → no micro_market_id FK; uses spatial join via ST_Intersects
"""
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class ZoneRiskResult:
    market: str
    zone: str
    far: float | None
    max_height_m: float | None
    ground_coverage_pct: float | None  # percentage (55 = 55%)
    setback_front_m: float | None
    setback_side_m: float | None
    overlay_risks: list[str] = field(default_factory=list)
    risk_level: str = "UNKNOWN"   # LOW | MEDIUM | HIGH | UNKNOWN


def check_zone_risk(market: str, zone: str = "R2") -> ZoneRiskResult:
    """Query regulatory_zones + overlay_constraints for a market/zone pair.

    Args:
        market: Market name (Yelahanka/Devanahalli/Hebbal). Case-insensitive.
        zone:   Zone code (R1/R2/C1, default R2). Case-insensitive.

    Returns:
        ZoneRiskResult with FAR, height, setbacks, overlay risks, and risk level.
        All numeric fields are None if not found. risk_level='UNKNOWN' if market unknown.
    """
    from utils.db import get_engine
    from sqlalchemy import text

    market = (market or "").strip()
    zone = (zone or "R2").strip().upper()

    if not market:
        logger.warning("[ZoneRisk] Empty market provided")
        return ZoneRiskResult(
            market=market, zone=zone, far=None, max_height_m=None,
            ground_coverage_pct=None, setback_front_m=None, setback_side_m=None,
            overlay_risks=["Market name is empty"],
            risk_level="UNKNOWN",
        )

    result = ZoneRiskResult(
        market=market, zone=zone,
        far=None, max_height_m=None, ground_coverage_pct=None,
        setback_front_m=None, setback_side_m=None,
    )

    try:
        with get_engine().connect() as conn:
            # regulatory_zones uses zone_type for market name, zone_code for zone
            row = conn.execute(text("""
                SELECT rz.far_base, rz.max_height_m, rz.ground_coverage_pct,
                       rz.front_setback_m, rz.side_setback_m
                FROM regulatory_zones rz
                WHERE rz.zone_type ILIKE :market AND rz.zone_code = :zone
                LIMIT 1
            """), {"market": f"%{market}%", "zone": zone}).fetchone()

            # overlay_constraints has no micro_market_id — use spatial join via
            # micro_markets.geom. If that fails (unpopulated geometry), return all
            # constraints globally as a fallback.
            overlays = []
            try:
                conn.execute(text("SAVEPOINT spatial_query"))
                overlays = conn.execute(text("""
                    SELECT oc.constraint_type, oc.description
                    FROM overlay_constraints oc
                    JOIN micro_markets mm ON ST_Intersects(oc.geom, mm.geom)
                    WHERE mm.name ILIKE :market
                """), {"market": f"%{market}%"}).fetchall()
                conn.execute(text("RELEASE SAVEPOINT spatial_query"))
            except Exception:
                conn.execute(text("ROLLBACK TO SAVEPOINT spatial_query"))
                conn.execute(text("RELEASE SAVEPOINT spatial_query"))
                overlays = conn.execute(text("""
                    SELECT oc.constraint_type, oc.description
                    FROM overlay_constraints oc
                """)).fetchall()
                if overlays:
                    logger.info("[ZoneRisk] Spatial join unavailable — returning all overlay constraints unfiltered (n=%d)", len(overlays))
    except Exception as exc:
        logger.warning("[ZoneRisk] DB query failed for market=%s zone=%s: %s", market, zone, exc)
        result.overlay_risks = [f"DB query failed: {exc}"]
        return result

    if row:
        result.far = float(row[0]) if row[0] is not None else None
        result.max_height_m = float(row[1]) if row[1] is not None else None
        # ground_coverage_pct is stored as a percentage (55 = 55%)
        result.ground_coverage_pct = float(row[2]) if row[2] is not None else None
        result.setback_front_m = float(row[3]) if row[3] is not None else None
        result.setback_side_m = float(row[4]) if row[4] is not None else None

        logger.debug("[ZoneRisk] market=%s zone=%s far=%s height=%s coverage=%s%%",
                      market, zone, result.far, result.max_height_m, result.ground_coverage_pct)
    else:
        logger.info("[ZoneRisk] No regulatory zone found for market=%s zone=%s", market, zone)

    risk_flags = []
    if overlays:
        seen_types = set()
        for ov_type, ov_desc in overlays:
            if ov_type in ("airport_funnel", "green_belt", "lake_buffer", "heritage_zone",
                           "forest_buffer", "rajakaluv_buffer", "ht_line_buffer"):
                flag = f"{ov_type}: {ov_desc}" if ov_desc else ov_type
                if flag not in seen_types:
                    risk_flags.append(flag)
                    seen_types.add(flag)

    result.overlay_risks = risk_flags

    if len(risk_flags) >= 2:
        result.risk_level = "HIGH"
    elif len(risk_flags) == 1:
        result.risk_level = "MEDIUM"
    elif row is not None:
        result.risk_level = "LOW"
    else:
        result.risk_level = "UNKNOWN"

    logger.info("[ZoneRisk] market=%s zone=%s risk_level=%s overlays=%d",
                market, zone, result.risk_level, len(risk_flags))
    return result


if __name__ == "__main__":
    import json
    for m in ("Yelahanka", "Devanahalli", "Hebbal", "Nonexistent"):
        result = check_zone_risk(m, "R2")
        print(f"\n[{m} R2]")
        print(json.dumps({k: v for k, v in result.__dict__.items() if not k.startswith("_")}, indent=2, default=str))
