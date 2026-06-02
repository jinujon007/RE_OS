"""
RE_OS — Zone Risk Checker (Tier 1 — Geospatial Foundation)
Uses GeoPandas spatial DataFrames for regulatory zone lookups and overlay
constraint spatial joins instead of raw SQL WHERE clauses.
Gracefully falls back to the original SQL-based implementation if GeoPandas
or PostGIS geometry data is unavailable at query time (not at import time).

Graceful degradation matrix:
┌──────────────────────┬──────────────────────┬─────────────────────────────┐
│ Condition            │ Zone data (FAR/etc.) │ Overlay constraints         │
├──────────────────────┼──────────────────────┼─────────────────────────────┤
│ GeoPandas + SQL OK   │ GeoPandas read_post..  .sjoin() spatial intersect  │
│ GeoPandas import err │ SQL query            │ SQL SAVEPOINT ST_Intersects  │
│ ST_Intersects fails  │ SQL query            │ Global scan (all overlays)  │
│ DB connection fails  │ None                 │ Error message in list       │
│                      │ risk_level=UNKNOWN   │ Early return                │
└──────────────────────┴──────────────────────┴─────────────────────────────┘
SAVEPOINT isolation ensures spatial query failure never aborts the
outer transaction. The function always returns a ZoneRiskResult, never raises.
"""
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class ZoneRiskResult:
    market: str
    zone: str
    far: float | None
    max_height_m: float | None
    ground_coverage_pct: float | None
    setback_front_m: float | None
    setback_side_m: float | None
    setback_rear_m: float | None
    overlay_risks: list[str] = field(default_factory=list)
    risk_level: str = "UNKNOWN"


def _load_zones_gdf(market: str, zone: str) -> tuple:
    """Load regulatory_zones + overlay_constraints as GeoDataFrames.
    Uses a single DB connection with SAVEPOINT isolation for the overlay query.
    Returns (zone_row_dict, overlay_risk_list) or (None, []) on failure.
    Returns (None, None) when GeoPandas itself is unavailable (triggers SQL fallback).
    """
    try:
        import geopandas as gpd
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError
        from utils.db import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SAVEPOINT gp_zone_query"))
            try:
                zones_gdf = gpd.read_postgis(
                    sql=text("""
                        SELECT rz.far_base, rz.max_height_m, rz.ground_coverage_pct,
                               rz.front_setback_m, rz.side_setback_m, rz.rear_setback_m,
                               rz.geom
                        FROM regulatory_zones rz
                        WHERE rz.zone_type ILIKE :market AND rz.zone_code = :zone
                        LIMIT 1
                    """),
                    con=conn,
                    params={"market": f"%{market}%", "zone": zone},
                    geom_col="geom",
                    crs="EPSG:4326",
                )
                conn.execute(text("RELEASE SAVEPOINT gp_zone_query"))
            except Exception:
                conn.execute(text("ROLLBACK TO SAVEPOINT gp_zone_query"))
                conn.execute(text("RELEASE SAVEPOINT gp_zone_query"))
                raise

            if zones_gdf.empty:
                return None, []

            row = zones_gdf.iloc[0]

            zone_row = {
                "far": float(row["far_base"]) if row["far_base"] is not None else None,
                "max_height_m": float(row["max_height_m"]) if row["max_height_m"] is not None else None,
                "ground_coverage_pct": float(row["ground_coverage_pct"]) if row["ground_coverage_pct"] is not None else None,
                "setback_front_m": float(row["front_setback_m"]) if row["front_setback_m"] is not None else None,
                "setback_side_m": float(row["side_setback_m"]) if row["side_setback_m"] is not None else None,
                "setback_rear_m": float(row["rear_setback_m"]) if row["rear_setback_m"] is not None else None,
            }

            zone_geom = row["geom"]
            if zone_geom is None:
                return zone_row, []

            conn.execute(text("SAVEPOINT gp_overlay_query"))
            try:
                overlays_gdf = gpd.read_postgis(
                    sql=text("""
                        SELECT oc.constraint_type, oc.description, oc.geom
                        FROM overlay_constraints oc
                        WHERE oc.geom IS NOT NULL
                    """),
                    con=conn,
                    geom_col="geom",
                    crs="EPSG:4326",
                )
                conn.execute(text("RELEASE SAVEPOINT gp_overlay_query"))
            except Exception:
                conn.execute(text("ROLLBACK TO SAVEPOINT gp_overlay_query"))
                conn.execute(text("RELEASE SAVEPOINT gp_overlay_query"))
                raise

            if overlays_gdf.empty:
                return zone_row, []

            if overlays_gdf.crs is None:
                overlays_gdf.set_crs("EPSG:4326", inplace=True)

            intersecting = overlays_gdf.sjoin(
                gpd.GeoDataFrame([{"geometry": zone_geom}], crs="EPSG:4326"),
                predicate="intersects",
            )

            risk_flags = []
            seen_types = set()
            for _, r in intersecting.iterrows():
                if not r.get("constraint_type") or r["constraint_type"] in seen_types:
                    continue
                flag = r["constraint_type"]
                if r.get("description"):
                    flag += f": {r['description']}"
                risk_flags.append(flag)
                seen_types.add(r["constraint_type"])

            return zone_row, risk_flags

    except ImportError:
        logger.debug("[ZoneRisk] GeoPandas not available — falling back to SQL path")
        return None, None
    except (SQLAlchemyError, Exception) as exc:
        logger.warning("[ZoneRisk] GeoPandas spatial query failed: %s", exc)
        return None, None


def _fallback_sql_query(market: str, zone: str) -> tuple:
    """Original SQL-based query as fallback when GeoPandas is unavailable.
    Returns (zone_row_dict, overlays_list, db_error_flag).
    db_error_flag is True if the DB connection itself failed.
    """
    from utils.db import get_engine
    from sqlalchemy import text

    result_row = None
    overlays = []
    db_error = False

    try:
        with get_engine().connect() as conn:
            row = conn.execute(text("""
                SELECT rz.far_base, rz.max_height_m, rz.ground_coverage_pct,
                       rz.front_setback_m, rz.side_setback_m, rz.rear_setback_m
                FROM regulatory_zones rz
                WHERE rz.zone_type ILIKE :market AND rz.zone_code = :zone
                LIMIT 1
            """), {"market": f"%{market}%", "zone": zone}).fetchone()

            if row:
                result_row = {
                    "far": float(row[0]) if row[0] is not None else None,
                    "max_height_m": float(row[1]) if row[1] is not None else None,
                    "ground_coverage_pct": float(row[2]) if row[2] is not None else None,
                    "setback_front_m": float(row[3]) if row[3] is not None else None,
                    "setback_side_m": float(row[4]) if row[4] is not None else None,
                    "setback_rear_m": float(row[5]) if row[5] is not None else None,
                }

            try:
                conn.execute(text("SAVEPOINT spatial_query"))
                try:
                    spatial_rows = conn.execute(text("""
                        SELECT oc.constraint_type, oc.description
                        FROM overlay_constraints oc
                        JOIN micro_markets mm ON ST_Intersects(oc.geom, mm.geom)
                        WHERE mm.name ILIKE :market
                    """), {"market": f"%{market}%"}).fetchall()
                    conn.execute(text("RELEASE SAVEPOINT spatial_query"))
                    overlays = list(spatial_rows)
                except Exception:
                    conn.execute(text("ROLLBACK TO SAVEPOINT spatial_query"))
                    conn.execute(text("RELEASE SAVEPOINT spatial_query"))
                    all_rows = conn.execute(text("""
                        SELECT oc.constraint_type, oc.description
                        FROM overlay_constraints oc
                    """)).fetchall()
                    if all_rows:
                        overlays = list(all_rows)
                        logger.info("[ZoneRisk] Spatial join unavailable — returning all overlay constraints (n=%d)", len(overlays))
            except Exception:
                logger.debug("[ZoneRisk] SAVEPOINT management failed")
    except Exception as exc:
        logger.warning("[ZoneRisk] SQL fallback query failed: %s", exc)
        db_error = True

    return result_row, overlays, db_error


def check_zone_risk(market: str, zone: str = "R2") -> ZoneRiskResult:
    market = (market or "").strip()
    zone = (zone or "R2").strip().upper()

    if not market:
        logger.warning("[ZoneRisk] Empty market provided")
        return ZoneRiskResult(
            market=market, zone=zone, far=None, max_height_m=None,
            ground_coverage_pct=None, setback_front_m=None, setback_side_m=None,
            setback_rear_m=None,
            overlay_risks=["Market name is empty"],
            risk_level="UNKNOWN",
        )

    result = ZoneRiskResult(market=market, zone=zone, far=None, max_height_m=None,
                            ground_coverage_pct=None, setback_front_m=None,
                            setback_side_m=None, setback_rear_m=None)

    zone_row, overlays = _load_zones_gdf(market, zone)

    if overlays is None:
        zone_row, raw_overlays, db_error = _fallback_sql_query(market, zone)
        risk_flags = []
        if raw_overlays:
            seen_types = set()
            for ov_type, ov_desc in raw_overlays:
                if not ov_type or ov_type in seen_types:
                    continue
                flag = f"{ov_type}: {ov_desc}" if ov_desc else ov_type
                risk_flags.append(flag)
                seen_types.add(ov_type)
        result.overlay_risks = risk_flags
        if db_error:
            if not risk_flags:
                result.overlay_risks = ["DB query failed — GeoPandas spatial and SQL fallback both unavailable"]
            # Early return — DB error is terminal, risk can't be assessed
            logger.info("[ZoneRisk] DB error — returning UNKNOWN for market=%s zone=%s", market, zone)
            return result
    else:
        result.overlay_risks = overlays

    if zone_row:
        result.far = zone_row["far"]
        result.max_height_m = zone_row["max_height_m"]
        result.ground_coverage_pct = zone_row["ground_coverage_pct"]
        result.setback_front_m = zone_row["setback_front_m"]
        result.setback_side_m = zone_row["setback_side_m"]
        result.setback_rear_m = zone_row["setback_rear_m"]

        logger.debug("[ZoneRisk] market=%s zone=%s far=%s height=%s coverage=%s%%",
                      market, zone, result.far, result.max_height_m, result.ground_coverage_pct)
    else:
        logger.info("[ZoneRisk] No regulatory zone found for market=%s zone=%s", market, zone)

    risk_flags = result.overlay_risks
    if len(risk_flags) >= 2:
        result.risk_level = "HIGH"
    elif len(risk_flags) == 1:
        result.risk_level = "MEDIUM"
    elif zone_row is not None:
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
