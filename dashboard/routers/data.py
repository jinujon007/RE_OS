"""
RE_OS Dashboard — Data/Market/Intel routes
"""

import csv
import glob
import io
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, Query, Response
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import text as _sa_text

from dashboard.state import (
    limiter, _get_sa_engine, templates, _normalize_market,
    _market_go_no_go, _cache_get, _cache_put,
    _embedder_instance, _embedder_lock, _search_cache,
    _SEARCH_CACHE_TTL, _SEARCH_CACHE_MAX,
    _estimated_cache, _ESTIMATED_CACHE_TTL,
    MARKET_SLUG, MARKET_CANONICAL,
    _pulse_cache, _pulse_cache_lock, _PULSE_CACHE_TTL, _PULSE_CACHE_MAX,
    _err_resp, _resolve_market, ErrorResponse,
)
from config.metrics import db_query_duration_seconds, digest_runs_total, _counter, _histogram
from utils.etag import compute_etag, check_etag, add_etag

logger = logging.getLogger("re_os.dashboard")

router = APIRouter(tags=["Data"])

# Separate router for /metrics (excluded from /api/v1 prefix — Prometheus scrapes this directly)
metrics_router = APIRouter(tags=["Metrics"])


# ── Response Models ─────────────────────────────────────────────────────


class OwnershipChainResponse(BaseModel):
    survey_no: str
    market: str | None = None
    khata_no: str | None = None
    owner_name: str | None = None
    previous_owner: str | None = None
    transfer_date: str | None = None
    area_acres: float | None = None
    govt_acquisition_notice: bool = False
    encumbrance_flag: bool = False
    fetched_at: str | None = None
    parcel_id: str | None = None
    parser_completeness_score: float | None = None


# ── Metrics ─────────────────────────────────────────────────────────────


@metrics_router.get(
    "/metrics",
    summary="Prometheus metrics endpoint",
    include_in_schema=False,
)
def metrics():
    from prometheus_client import generate_latest
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4",
    )


# ── DB State ────────────────────────────────────────────────────────────


@router.get(
    "/db/state",
    summary="Database record counts and market summary",
)
@limiter.limit("60/minute")
async def db_state(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            state = {}
            state["rera_projects"] = conn.execute(
                _sa_text("SELECT COUNT(*) FROM rera_projects")
            ).fetchone()[0]
            state["listings"] = conn.execute(
                _sa_text("SELECT COUNT(*) FROM listings")
            ).fetchone()[0]
            state["kaveri_registrations"] = conn.execute(
                _sa_text("SELECT COUNT(*) FROM kaveri_registrations")
            ).fetchone()[0]
            state["guidance_values"] = conn.execute(
                _sa_text("SELECT COUNT(*) FROM guidance_values")
            ).fetchone()[0]
            markets = conn.execute(
                _sa_text("""
                SELECT mm.name,
                       COUNT(DISTINCT rp.id) AS projects,
                       ROUND(AVG(l.price_psf)::numeric, 0) AS avg_psf
                FROM micro_markets mm
                LEFT JOIN rera_projects rp ON rp.micro_market_id = mm.id
                LEFT JOIN listings l ON l.micro_market_id = mm.id
                                    AND l.price_psf IS NOT NULL
                                    AND l.price_psf > 1000
                                    AND l.price_psf < 50000
                GROUP BY mm.name ORDER BY mm.name
            """)
            ).fetchall()
            state["markets"] = [
                {"name": r[0], "projects": r[1], "avg_psf": int(r[2]) if r[2] else None}
                for r in markets
            ]
            recent = conn.execute(
                _sa_text("""
                SELECT micro_market, started_at, status, duration_seconds
                FROM agent_runs ORDER BY started_at DESC LIMIT 5
            """)
            ).fetchall()
            state["recent_runs"] = [
                {
                    "market": r[0], "start_time": r[1].isoformat() if r[1] else None,
                    "status": r[2], "duration": r[3],
                }
                for r in recent
            ]
        etag = compute_etag(state)
        resp = check_etag(request, etag)
        if resp:
            return resp
        return JSONResponse(content=state, headers={"ETag": f'"{etag}"'})
    except Exception as e:
        logger.error("[db_state] %s", e)
        return _err_resp("database query failed", request, 500, "Data")


@router.get("/db/tables", summary="View contents of key DB views")
@limiter.limit("30/minute")
async def db_tables(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            with db_query_duration_seconds.labels(query_name="v_market_inventory").time():
                mi_rows = conn.execute(
                    _sa_text("SELECT * FROM v_market_inventory")
                ).fetchall()
                mi_cols = mi_rows[0]._mapping.keys() if mi_rows else []
                market_inventory = [dict(zip(mi_cols, r)) for r in mi_rows]
            with db_query_duration_seconds.labels(query_name="v_developer_scorecard").time():
                ds_rows = conn.execute(
                    _sa_text("""
                    SELECT developer, grade, total_projects, total_units,
                           avg_absorption_pct, completed, delayed, markets_active_in
                    FROM v_developer_scorecard LIMIT 50
                """)
                ).fetchall()
                ds_cols = ds_rows[0]._mapping.keys() if ds_rows else []
                developer_scorecard = [dict(zip(ds_cols, r)) for r in ds_rows]
            with db_query_duration_seconds.labels(query_name="v_active_projects").time():
                ap_rows = conn.execute(
                    _sa_text("""
                    SELECT project_name, developer_name, micro_market, project_status,
                           total_units, unsold_units, absorption_pct
                    FROM v_active_projects LIMIT 100
                """)
                ).fetchall()
                ap_cols = ap_rows[0]._mapping.keys() if ap_rows else []
                active_projects = [dict(zip(ap_cols, r)) for r in ap_rows]
        return {
            "market_inventory": market_inventory,
            "developer_scorecard": developer_scorecard,
            "active_projects": active_projects,
        }
    except Exception as e:
        logger.error("[db_tables] %s", e)
        return _err_resp("database query failed", request, 500, "Data")


# ── Reports ─────────────────────────────────────────────────────────────


@router.get(
    "/reports/{market}",
    summary="Latest intel report text for a market",
)
@limiter.limit("30/minute")
async def get_report(request: Request, market: str):
    canonical = _normalize_market(market)
    if not canonical or canonical == "all":
        return _err_resp("invalid market", request, 400, "Data")
    slug = MARKET_SLUG.get(canonical)
    if not slug:
        return _err_resp("invalid market", request, 400, "Data")
    pattern = f"/app/outputs/{slug}/intel_report_*.txt"
    files = sorted(glob.glob(pattern))
    if not files:
        return {"content": None, "file": None}
    latest = files[-1]
    with open(latest, encoding="utf-8") as f:
        content = f.read()
    return {"content": content, "file": os.path.basename(latest)}


@router.get(
    "/intel/cards",
    summary="Market summary cards for dashboard UI",
)
@limiter.limit("60/minute")
async def intel_cards(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                SELECT mm.name,
                       COUNT(DISTINCT rp.id) AS projects,
                       ROUND(AVG(l.price_psf)::numeric, 0) AS avg_psf
                FROM micro_markets mm
                LEFT JOIN rera_projects rp ON rp.micro_market_id = mm.id
                LEFT JOIN listings l ON l.micro_market_id = mm.id
                                    AND l.price_psf IS NOT NULL
                                    AND l.price_psf > 1000
                                    AND l.price_psf < 50000
                GROUP BY mm.name ORDER BY mm.name
            """)
            ).fetchall()
        now = time.time()
        cards = []
        for row in rows:
            market_name = row[0]
            slug = MARKET_SLUG.get(market_name, market_name.lower())
            cached = _estimated_cache.get(market_name)
            if cached and cached[1] > now:
                is_estimated = cached[0]
            else:
                report_files = sorted(glob.glob(f"/app/outputs/{slug}/intel_report_*.txt"))
                is_estimated = False
                if report_files:
                    try:
                        with open(report_files[-1], encoding="utf-8") as rf:
                            is_estimated = "[ESTIMATED DATA" in rf.read(4096)
                    except Exception:
                        pass
                _estimated_cache[market_name] = (is_estimated, now + _ESTIMATED_CACHE_TTL)
            cards.append({
                "market": market_name,
                "active_projects": int(row[1] or 0),
                "projects": int(row[1] or 0),
                "avg_psf": int(row[2]) if row[2] else None,
                "go_no_go": _market_go_no_go(
                    int(row[1] or 0), int(row[2]) if row[2] else None, is_estimated
                ),
                "download_url": f"/intel/download?market={slug}" if slug else None,
                "estimated": is_estimated,
            })
        data = {"cards": cards}
        etag = compute_etag(data)
        resp = check_etag(request, etag)
        if resp:
            return resp
        return JSONResponse(content=data, headers={"ETag": f'"{etag}"'})
    except Exception as e:
        logger.error("[intel_cards] %s", e)
        return _err_resp("failed to load market cards", request, 500, "Data")


@router.get(
    "/intel/search",
    summary="Semantic search over past intel reports",
)
@limiter.limit("20/minute")
async def intel_search(request: Request, q: str = Query(""), market: str = Query("")):
    query_text = (q or "").strip()[:200]
    market_param = _normalize_market(market)
    if any(ord(c) < 32 and c not in "\t\n\r" for c in query_text):
        return JSONResponse({
            "results": [], "query": query_text[:50],
            "error": "invalid characters in query",
        }, status_code=400)
    if not query_text:
        return {"results": [], "query": query_text}
    market_filter = market_param if market_param and market_param != "all" else None
    cache_key = f"{query_text}:::{market_filter or ''}"
    now = time.time()
    cached = _cache_get(cache_key)
    if cached and cached[1] > now:
        return {"results": cached[0], "query": query_text, "market": market, "cached": True}
    try:
        global _embedder_instance
        if _embedder_instance is None:
            with _embedder_lock:
                if _embedder_instance is None:
                    from utils.embedder import IntelEmbedder
                    _embedder_instance = IntelEmbedder()
        results = _embedder_instance.search(query_text, market=market_filter, n=5)
        _cache_put(cache_key, (results, now + _SEARCH_CACHE_TTL))
        return {"results": results, "query": query_text, "market": market}
    except Exception as e:
        logger.warning("[intel_search] search failed: q=%s market=%s: %s", query_text[:40], market_filter, e)
        return {"results": [], "query": query_text, "error": "search unavailable - index not built yet"}


@router.get(
    "/intel/download",
    summary="Download intel report as txt or csv",
)
def download_intel(market: str = Query(""), format: str = Query("txt")):
    canonical = _normalize_market(market)
    fmt = format.lower()
    if fmt == "csv":
        return _download_intel_csv(canonical)
    if not canonical or canonical == "all":
        return _err_resp("invalid market", None, 400, "Data")
    slug = MARKET_SLUG.get(canonical)
    pattern = f"/app/outputs/{slug}/intel_report_*.txt"
    files = sorted(glob.glob(pattern))
    if not files:
        return _err_resp("no report found", None, 404, "Data")
    with open(files[-1], encoding="utf-8") as f:
        content = f.read()
    return Response(content=content, media_type="text/plain")


def _download_intel_csv(canonical: str | None):
    if not canonical:
        return _err_resp("invalid market", None, 400, "Data")
    try:
        with _get_sa_engine().connect() as conn:
            params = {}
            where = ""
            if canonical != "all":
                where = "WHERE mm.name = :m"
                params["m"] = canonical
            db_rows = conn.execute(
                _sa_text(f"""
                SELECT mm.name,
                       COUNT(DISTINCT rp.id) AS active_projects,
                       ROUND(AVG(l.price_psf)::numeric, 0) AS avg_psf
                FROM micro_markets mm
                LEFT JOIN rera_projects rp ON rp.micro_market_id = mm.id
                LEFT JOIN listings l ON l.micro_market_id = mm.id
                                    AND l.price_psf IS NOT NULL
                                    AND l.price_psf > 1000
                                    AND l.price_psf < 50000
                {where}
                GROUP BY mm.name ORDER BY mm.name
            """),
                params,
            ).fetchall()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["market", "active_projects", "avg_psf", "go_no_go", "estimated"])
        now = time.time()
        for market_name, active_projects, avg_psf in db_rows:
            slug = MARKET_SLUG.get(market_name, market_name.lower())
            cached = _estimated_cache.get(market_name)
            if cached and cached[1] > now:
                estimated = cached[0]
            else:
                report_files = sorted(glob.glob(f"/app/outputs/{slug}/intel_report_*.txt"))
                estimated = False
                if report_files:
                    try:
                        with open(report_files[-1], encoding="utf-8") as rf:
                            estimated = "[ESTIMATED DATA" in rf.read(4096)
                    except Exception:
                        pass
                _estimated_cache[market_name] = (estimated, now + _ESTIMATED_CACHE_TTL)
            projects = int(active_projects or 0)
            psf = int(avg_psf) if avg_psf else None
            writer.writerow([market_name, projects, psf or "", _market_go_no_go(projects, psf, estimated), estimated])
        filename = "intel_cards.csv" if canonical == "all" else f"intel_{MARKET_SLUG.get(canonical, canonical.lower())}.csv"
        return Response(
            content=out.getvalue(), media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error("[download_intel_csv] %s", e)
        return _err_resp("failed to export intel csv", None, 500, "Data")


# ── PropContext Delta (GATE-134) ───────────────────────────────────────

# Prometheus metrics for propcontext usage
_propcontext_delta_total = _counter(
    "propcontext_delta_total",
    "PropContext delta endpoint invocations by market and pc_status",
    ["market", "pc_status"],
)


class PropContextProject(BaseModel):
    rera_id: str | None = None
    project_name: str | None = None
    developer: str | None = None
    project_status: str | None = None
    launch_date: str | None = None
    locality: str | None = None
    rera_psf_min: float | None = None
    rera_psf_max: float | None = None


class PropContextDeltaResponse(BaseModel):
    market: str
    propcontext_status: str
    re_os_only: list[PropContextProject]
    propcontext_only: list[PropContextProject]
    intersection: list[PropContextProject]
    re_os_count: int
    propcontext_count: int
    intersection_count: int = 0
    re_os_coverage_pct: float = 0.0
    note: str = ""


def _normalize_name(name: str | None) -> str:
    """Normalize a project name for fuzzy comparison.

    Lowercases, strips whitespace, removes parenthetical suffixes,
    collapses multiple spaces, strips common suffixes like ' Pvt Ltd'.
    """
    if not name:
        return ""
    normalized = name.strip().lower()
    # Remove parenthetical content like "(Phase 2)" or "(Previously ...)"
    normalized = re.sub(r"\s*\([^)]*\)", "", normalized)
    # Remove common legal suffixes
    normalized = re.sub(r"\s+(pvt|ltd|private\s+limited|llp)$", "", normalized)
    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _names_match(a: str | None, b: str | None) -> bool:
    """Check if two project names refer to the same project.

    Uses exact match of normalized names, then substring containment.
    """
    na = _normalize_name(a)
    nb = _normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Substring: one name contains the other
    if len(na) >= 5 and len(nb) >= 5:
        if na in nb or nb in na:
            return True
    return False


@router.get(
    "/intel/propcontext-delta/{market}",
    summary="PropContext vs RE_OS cross-reference delta",
    response_model=PropContextDeltaResponse,
)
@limiter.limit("10/minute")
async def propcontext_delta(market: str, request: Request):
    """Compare projects between PropContext MCP and RE_OS database.

    Returns delta analysis:
    - re_os_only: projects in RE_OS not found in PropContext
    - propcontext_only: projects in PropContext not found in RE_OS
    - intersection: projects present in both sources
    - re_os_coverage_pct: percentage of PropContext projects covered by RE_OS
    """
    canonical = _resolve_market(market)
    if not canonical:
        _propcontext_delta_total.labels(market=market, pc_status="invalid_market").inc()
        return _err_resp(f"invalid market: {market}", request, 400, "Data")

    re_os_projects_raw: list[dict[str, Any]] = []
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT rp.rera_id, rp.project_name, d.name AS developer,
                           rp.project_status,
                           rp.launch_date::text AS launch_date,
                           rp.locality,
                           rp.price_min_psf AS rera_psf_min,
                           rp.price_max_psf AS rera_psf_max
                    FROM rera_projects rp
                    JOIN micro_markets m ON m.id = rp.micro_market_id
                    LEFT JOIN developers d ON d.id = rp.developer_id
                    WHERE m.name = :m
                      AND (rp.rera_id IS NOT NULL OR rp.project_name IS NOT NULL)
                    ORDER BY rp.project_name
                """),
                {"m": canonical},
            ).fetchall()
        re_os_projects_raw = [dict(r._mapping) for r in rows]
    except Exception as exc:
        logger.warning("[propcontext-delta] RE_OS query failed: %s", exc)
        _propcontext_delta_total.labels(market=canonical, pc_status="db_error").inc()
        return _err_resp("RE_OS query failed", request, 500, "Data")

    # Query PropContext
    from tools.propcontext_tool import PropContextSearchTool

    search_tool = PropContextSearchTool()
    pc_result = search_tool._run(json.dumps({"query": canonical, "market": canonical}))
    try:
        pc_data = json.loads(pc_result)
    except (json.JSONDecodeError, TypeError):
        pc_data = {"status": "unavailable", "results": []}

    pc_status = pc_data.get("status", "unavailable")
    if pc_status == "unavailable":
        _propcontext_delta_total.labels(market=canonical, pc_status="unavailable").inc()
        re_os_projects = [PropContextProject(**p) for p in re_os_projects_raw]
        return PropContextDeltaResponse(
            market=canonical,
            propcontext_status="unavailable",
            re_os_only=re_os_projects,
            propcontext_only=[],
            intersection=[],
            re_os_count=len(re_os_projects),
            propcontext_count=0,
            note="PropContext MCP unreachable — returning RE_OS projects only",
        )

    pc_projects_raw = pc_data.get("results", [])
    if not isinstance(pc_projects_raw, list):
        pc_projects_raw = []

    # Compute delta with fuzzy name matching
    matched_re_os: set[int] = set()
    matched_pc: set[int] = set()

    for i, re_p in enumerate(re_os_projects_raw):
        for j, pc_p in enumerate(pc_projects_raw):
            if j in matched_pc:
                continue
            if isinstance(pc_p, dict) and _names_match(
                re_p.get("project_name"), pc_p.get("project_name")
            ):
                matched_re_os.add(i)
                matched_pc.add(j)
                break

    re_os_only_raw = [p for i, p in enumerate(re_os_projects_raw) if i not in matched_re_os]
    pc_only_raw = [p for i, p in enumerate(pc_projects_raw) if i not in matched_pc]
    intersection_raw = [p for i, p in enumerate(re_os_projects_raw) if i in matched_re_os]

    re_os_coverage = (
        round(len(matched_re_os) / max(len(pc_projects_raw), 1) * 100, 1)
        if pc_projects_raw
        else 0.0
    )

    _propcontext_delta_total.labels(market=canonical, pc_status="ok").inc()

    return PropContextDeltaResponse(
        market=canonical,
        propcontext_status="ok",
        re_os_only=[PropContextProject(**p) for p in re_os_only_raw],
        propcontext_only=[
            PropContextProject(project_name=p.get("project_name")) if isinstance(p, dict) else PropContextProject()
            for p in pc_only_raw
        ],
        intersection=[PropContextProject(**p) for p in intersection_raw],
        re_os_count=len(re_os_projects_raw),
        propcontext_count=len(pc_projects_raw),
        intersection_count=len(matched_re_os),
        re_os_coverage_pct=re_os_coverage,
    )


# ── Market Map ──────────────────────────────────────────────────────────


@router.get(
    "/market/map/{market}",
    summary="Folium map HTML with project markers and PSF color gradient",
)
async def market_map(market: str):
    try:
        import folium
        from folium.plugins import MarkerCluster
        from utils.db import get_engine
        from sqlalchemy import text
        canonical = _normalize_market(market)
        if not canonical:
            return _err_resp("invalid market", None, 400, "Data")
        with get_engine().connect() as conn:
            center = conn.execute(
                text("SELECT ST_X(centroid), ST_Y(centroid) FROM micro_markets WHERE name ILIKE :m LIMIT 1"),
                {"m": f"%{canonical}%"},
            ).fetchone()
        if not center:
            return _err_resp("market not found", None, 404, "Data")
        m = folium.Map(location=[center[1], center[0]], zoom_start=13, tiles="CartoDB dark_matter")
        with get_engine().connect() as conn:
            projects = conn.execute(
                text("""
                    SELECT rp.project_name, d.name, ST_X(rp.geom), ST_Y(rp.geom),
                           rp.price_min_psf, rp.price_max_psf
                    FROM rera_projects rp
                    JOIN developers d ON d.id = rp.developer_id
                    JOIN micro_markets m ON m.id = rp.micro_market_id
                    WHERE m.name ILIKE :m AND rp.geom IS NOT NULL
                    LIMIT 200
                """),
                {"m": f"%{canonical}%"},
            ).fetchall()
        marker_cluster = MarkerCluster().add_to(m)
        for proj in projects:
            name, dev, lon, lat, psf_min, psf_max = proj
            if lon and lat:
                avg_psf = (float(psf_min or 0) + float(psf_max or 0)) / 2 if psf_min or psf_max else 0
                if avg_psf < 4000:
                    color = "#3fb950"
                elif avg_psf < 6000:
                    color = "#f0a020"
                elif avg_psf < 10000:
                    color = "#f85149"
                else:
                    color = "#9b7ec7"
                psf_str = f"\u20b9{avg_psf:,.0f} PSF" if avg_psf else "PSF unknown"
                folium.CircleMarker(
                    location=[lat, lon], radius=8, color=color, fill=True, fill_opacity=0.7,
                    popup=f"<b>{name}</b><br>{dev}<br>{psf_str}",
                ).add_to(marker_cluster)
        legend_html = """
        <div style="position:fixed;bottom:20px;left:20px;z-index:1000;background:#0f1520;border:1px solid #2a3a55;border-radius:4px;padding:8px;font-family:'Courier New',monospace;font-size:10px;">
            <div style="color:#c9d1d9;margin-bottom:4px;">PSF Range</div>
            <div><span style="color:#3fb950;">\u25cf</span> &lt; \u20b94,000</div>
            <div><span style="color:#f0a020;">\u25cf</span> \u20b94,000\u20136,000</div>
            <div><span style="color:#f85149;">\u25cf</span> \u20b96,000\u201310,000</div>
            <div><span style="color:#9b7ec7;">\u25cf</span> &gt; \u20b910,000</div>
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))
        return HTMLResponse(content=m._repr_html_())
    except ImportError as exc:
        logger.warning("[market_map] folium not installed: %s", exc)
        return _err_resp("folium not installed", None, 500, "Data")
    except Exception as exc:
        logger.warning("[market_map] Failed for %s: %s", market, exc)
        return _err_resp(str(exc), None, 500, "Data")


@router.get(
    "/market/psf-trend/{market}",
    summary="Monthly PSF trend data for Chart.js line chart",
)
async def psf_trend(market: str):
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        canonical = _normalize_market(market)
        if not canonical:
            return _err_resp("invalid market", None, 400, "Data")
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT DATE_TRUNC('month', snapshot_date) AS month,
                           ROUND(AVG(avg_psf)::numeric, 0) AS avg_psf
                    FROM project_snapshots ps
                    JOIN micro_markets m ON m.id = ps.micro_market_id
                    WHERE m.name ILIKE :m AND ps.avg_psf IS NOT NULL
                    GROUP BY DATE_TRUNC('month', snapshot_date)
                    ORDER BY month
                """),
                {"m": f"%{canonical}%"},
            ).fetchall()
        data = [
            {
                "month": r[0].strftime("%Y-%m") if hasattr(r[0], "strftime") else str(r[0])[:7],
                "psf": float(r[1]),
            }
            for r in rows
        ]
        return {"market": canonical, "trend": data}
    except Exception as exc:
        logger.warning("[psf_trend] Failed: %s", exc)
        return _err_resp(str(exc), None, 500, "Data")


@router.get(
    "/market/kepler-data/{market}",
    summary="GeoJSON FeatureCollection for Kepler.gl density map",
)
async def kepler_data(market: str):
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        canonical = _normalize_market(market)
        if not canonical:
            return _err_resp("invalid market", None, 400, "Data")
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT rp.project_name, d.name, rp.price_min_psf, rp.price_max_psf,
                           rp.total_units, rp.project_status,
                           ST_AsGeoJSON(rp.geom) AS geojson
                    FROM rera_projects rp
                    JOIN developers d ON d.id = rp.developer_id
                    JOIN micro_markets m ON m.id = rp.micro_market_id
                    WHERE m.name ILIKE :m AND rp.geom IS NOT NULL
                    LIMIT 1000
                """),
                {"m": f"%{canonical}%"},
            ).fetchall()
        features = []
        for r in rows:
            geom = json.loads(r[6]) if r[6] else None
            if geom:
                features.append({
                    "type": "Feature", "geometry": geom,
                    "properties": {
                        "project": r[0], "developer": r[1],
                        "price_min_psf": float(r[2]) if r[2] else None,
                        "price_max_psf": float(r[3]) if r[3] else None,
                        "total_units": r[4], "status": r[5],
                    },
                })
        return {"type": "FeatureCollection", "features": features}
    except Exception as exc:
        logger.warning("[kepler_data] Failed: %s", exc)
        return _err_resp(str(exc), None, 500, "Data")


@router.get(
    "/market/accessibility",
    summary="Travel-time accessibility scores for a market",
)
async def market_accessibility(
    market: str = Query(default="Yelahanka", description="Market name"),
):
    try:
        from utils.db import get_engine
        from sqlalchemy import text as sa_text
        canonical = _normalize_market(market)
        if not canonical:
            return _err_resp("invalid market", None, 400, "Data")
        with get_engine().connect() as conn:
            rows = conn.execute(
                sa_text("""
                    SELECT destination_name, travel_time_min, distance_km, measured_at, accessibility_score
                    FROM accessibility_scores
                    WHERE market = :market
                      AND measured_at > NOW() - INTERVAL '30 days'
                    ORDER BY measured_at DESC
                """),
                {"market": canonical},
            ).fetchall()
        if not rows:
            return _err_resp("no accessibility data for market", None, 404, "Data")
        latest = {}
        latest_dt = {}
        for r in rows:
            dest = str(r[0])
            if dest not in latest:
                measured = r[3]
                measured_iso = measured.isoformat() if hasattr(measured, "isoformat") else str(measured)
                latest_dt[dest] = measured
                latest[dest] = {
                    "name": dest, "travel_time_min": float(r[1]),
                    "distance_km": float(r[2]) if r[2] else None,
                    "measured_at": measured_iso, "accessibility_score": float(r[4]) if r[4] else 0.0,
                }
        destinations = list(latest.values())
        total_score = sum(d["accessibility_score"] for d in destinations)
        last_updated = None
        if latest_dt:
            last_updated = max(latest_dt.values())
            last_updated = last_updated.isoformat() if hasattr(last_updated, "isoformat") else str(last_updated)
        return {
            "market": canonical, "accessibility_score": round(total_score, 4),
            "destinations": destinations, "last_updated": last_updated,
        }
    except Exception as exc:
        logger.warning("[market_accessibility] Failed: %s", exc)
        return _err_resp(str(exc), None, 500, "Data")


# ── Data Freshness ──────────────────────────────────────────────────────


@router.get(
    "/data/freshness",
    summary="Data freshness per source per market",
)
@limiter.limit("30/minute")
async def data_freshness(request: Request, market: str = Query(None)):
    from utils.data_freshness import get_source_status
    market_filter = market.strip() if market else None
    rows = get_source_status(market=market_filter)
    return {"freshness": rows}


# ── Memory Explorer ─────────────────────────────────────────────────────


@router.get(
    "/memory/explorer",
    summary="Paginated agent memory explorer with filters",
)
@limiter.limit("60/hour")
async def memory_explorer(
    request: Request,
    market: str = Query(default=None, description="Market filter"),
    agent_id: str = Query(default=None, description="Agent ID filter"),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum confidence threshold"),
    days: int = Query(default=30, ge=7, le=365, description="Lookback window in days"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
):
    market_filter = _normalize_market(market) if market else None
    MAX_FACT_LENGTH = 10000
    MAX_PER_PAGE = 100
    SAFE_PER_PAGE = min(per_page, MAX_PER_PAGE)
    safe_offset = (page - 1) * SAFE_PER_PAGE
    try:
        with _get_sa_engine().connect() as conn:
            where = ["confidence >= :mc", "last_updated >= NOW() - :days * INTERVAL '1 day'"]
            params = {"mc": min_confidence, "days": days}
            if market_filter:
                where.append("market ILIKE :m")
                params["m"] = f"%{market_filter}%"
            if agent_id:
                where.append("agent_id = :aid")
                params["aid"] = agent_id
            where_sql = " AND ".join(where)
            params["lim"] = SAFE_PER_PAGE
            params["off"] = safe_offset
            total = conn.execute(
                _sa_text(f"SELECT COUNT(*) FROM agent_memories WHERE {where_sql}"),
                {k: v for k, v in params.items() if k not in ("lim", "off")},
            ).scalar() or 0
            rows = conn.execute(
                _sa_text(f"""
                SELECT id, agent_id, market, fact, confidence,
                       COALESCE(source_count, 0) as source_count,
                       last_updated, created_at
                FROM agent_memories
                WHERE {where_sql}
                ORDER BY confidence DESC, last_updated DESC
                LIMIT :lim OFFSET :off
            """),
                params,
            ).fetchall()
        memories = []
        for r in rows:
            fact_raw = str(r[3]) if r[3] else ""
            memories.append({
                "id": str(r[0]),
                "agent_id": str(r[1]) if r[1] else "",
                "market": str(r[2]) if r[2] else "",
                "fact": fact_raw[:MAX_FACT_LENGTH],
                "fact_truncated": len(fact_raw) > MAX_FACT_LENGTH,
                "confidence": round(float(r[4]), 3) if r[4] is not None else 0.0,
                "source_count": int(r[5]) if r[5] is not None else 0,
                "last_updated": r[6].isoformat() if r[6] else None,
                "created_at": r[7].isoformat() if r[7] else None,
            })
        return {"total": total, "page": page, "per_page": SAFE_PER_PAGE, "memories": memories}
    except Exception as e:
        logger.error("[memory_explorer] page=%s market=%s agent=%s err=%s", page, market_filter, agent_id, e)
        return _err_resp("failed to query agent memories", request, 500, "Memory")


@router.get(
    "/memory/conflict-count",
    summary="Unresolved conflict count for nav badge",
)
@limiter.limit("60/hour")
async def memory_conflict_count(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            count = conn.execute(
                _sa_text("""
                SELECT COUNT(*) FROM agent_memories
                WHERE fact ILIKE '%CONFLICT%' OR fact ILIKE '%conflict%'
            """),
            ).scalar() or 0
        return {"unresolved_conflicts": int(count)}
    except Exception:
        logger.warning("[memory_conflict_count] DB unavailable — returning 0")
        return {"unresolved_conflicts": 0}


# ── LLM Provider Health ─────────────────────────────────────────────────


@router.get(
    "/health/llm",
    summary="LLM provider health — circuit breaker states + provider availability",
)
@limiter.limit("30/minute")
async def health_llm(request: Request):
    try:
        from config.llm_router import get_router_status, get_circuit_states
        status = get_router_status()
        circuits = get_circuit_states()
        providers = status.get("providers", {})
        available = [p for p, cfg in providers.items() if cfg]
        failed = [p for p, cfg in providers.items() if not cfg]
        return {
            "configured": len(available) > 0,
            "providers_available": available,
            "providers_failed": failed,
            "circuit_state": circuits,
            "recommended_model": available[0] if available else None,
        }
    except Exception as exc:
        logger.warning("[health_llm] %s", exc)
        return {
            "configured": False, "providers_available": [],
            "providers_failed": ["router_error"], "circuit_state": {}, "recommended_model": None,
        }


# ── Backup Health ───────────────────────────────────────────────────────


@router.get(
    "/health/backup",
    summary="Last DB backup timestamp",
)
@limiter.limit("30/minute")
async def health_backup(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            row = conn.execute(
                _sa_text("""
                SELECT created_at FROM agent_runs
                WHERE agent_id = 'backup' AND event_type = 'db_backup'
                ORDER BY created_at DESC LIMIT 1
            """)
            ).fetchone()
        if row:
            return {"last_backup": row[0].isoformat() if row[0] else None, "status": "ok"}
        return {"last_backup": None, "status": "never_run"}
    except Exception as e:
        logger.error("[health_backup] %s", e)
        return {"last_backup": None, "status": "never_run"}


# ── Scheduler Health ────────────────────────────────────────────────────


@router.get(
    "/scheduler/health",
    summary="Scheduler job health — last run status per job ID (7d window)",
)
@limiter.limit("30/minute")
async def scheduler_health(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT agent_name, event_type, status, started_at, completed_at,
                           CASE WHEN started_at > NOW() - INTERVAL '24 hours' THEN 1 ELSE 0 END AS in_last_24h
                    FROM agent_runs
                    WHERE started_at > NOW() - INTERVAL '7 days'
                    ORDER BY started_at DESC
                    LIMIT 500
                """)
            ).fetchall()
        jobs = {}
        for r in rows:
            jid = str(r[0]) if r[0] else "unknown"
            if jid not in jobs:
                jobs[jid] = {
                    "job_id": jid, "event_type": r[1],
                    "last_status": r[2], "last_run": r[3].isoformat() if r[3] else None,
                    "completed_at": r[4].isoformat() if r[4] else None,
                    "last_24h_passes": 0, "last_24h_failures": 0,
                }
            if r[5]:
                status = r[2]
                if status == "success":
                    jobs[jid]["last_24h_passes"] += 1
                elif status in ("failed", "error"):
                    jobs[jid]["last_24h_failures"] += 1
        return {
            "jobs": sorted(jobs.values(), key=lambda j: j["last_run"] or "", reverse=True),
            "total_jobs": len(jobs),
        }
    except Exception as e:
        logger.error("[scheduler_health] %s", e)
        return _err_resp("database query failed", request, 500, "Data")


# ── Data Provenance ─────────────────────────────────────────────────────


@router.get(
    "/data/provenance",
    summary="Data provenance breakdown per market (live vs seed)",
)
@limiter.limit("60/hour")
async def data_provenance(
    request: Request,
    market: str = Query(default=None, description="Optional market filter"),
):
    try:
        with _get_sa_engine().connect() as conn:
            where = []
            params = {}
            if market:
                where.append("mm.name ILIKE :mkt")
                params["mkt"] = f"%{market}%"
            where_clause = (" WHERE " + " AND ".join(where)) if where else ""
            rows = conn.execute(
                _sa_text(f"""
                SELECT mm.name, rp.data_source, COUNT(*) as cnt
                FROM rera_projects rp
                JOIN micro_markets mm ON mm.id = rp.micro_market_id
                {where_clause}
                GROUP BY mm.name, rp.data_source
                ORDER BY mm.name
            """),
                params,
            ).fetchall()
        markets = {}
        for row in rows:
            mkt = str(row[0]) if row[0] else "Unknown"
            ds = str(row[1]) if row[1] else "seed_estimated"
            cnt = int(row[2]) if row[2] else 0
            if mkt not in markets:
                markets[mkt] = {"total": 0, "live": 0, "seed": 0, "manual": 0, "live_pct": 0.0}
            markets[mkt]["total"] += cnt
            if ds == "portal_scraped":
                markets[mkt]["live"] += cnt
            elif ds == "manual_entry":
                markets[mkt]["manual"] += cnt
            else:
                markets[mkt]["seed"] += cnt
        for data in markets.values():
            total = data["total"]
            live = data["live"]
            data["live_pct"] = round((live / total) * 100, 1) if total > 0 else 0.0
            if data["live_pct"] < 30:
                data["guidance"] = "Run RERA scraper — live data below 30% threshold"
            elif data["live_pct"] < 70:
                data["guidance"] = "Monitor — live data moderate, continue scraping"
            else:
                data["guidance"] = "Healthy — live data above 70%"
        if market and not markets:
            return {market: {"total": 0, "live": 0, "seed": 0, "manual": 0, "live_pct": 0.0, "guidance": "No data for this market"}}
        etag = compute_etag(markets)
        resp = check_etag(request, etag)
        if resp:
            return resp
        return JSONResponse(content=markets, headers={"ETag": f'"{etag}"'})
    except Exception as e:
        logger.error("[data_provenance] err=%s", e)
        return _err_resp("failed to query data provenance", request, 500, "Data")


# ── Scraper Reliability ─────────────────────────────────────────────────


@router.get(
    "/scraper/reliability",
    summary="Scraper reliability scores for all scouts",
)
@limiter.limit("60/hour")
async def scraper_reliability(
    request: Request, days: int = Query(default=30, ge=1, le=365)
):
    try:
        from config.scraper_registry import SCRAPER_NAMES
        from utils.scraper_reliability import compute_scraper_reliability
        results = []
        for name in SCRAPER_NAMES:
            try:
                result = compute_scraper_reliability(name, days=days)
                results.append(result)
            except Exception as exc:
                logger.warning("[scraper_reliability] %s: %s", name, exc)
                results.append({"scraper": name, "runs": 0, "successes": 0, "reliability_score": 0.0, "last_run": None})
        return {r["scraper"]: r for r in results}
    except Exception as e:
        logger.error("[scraper_reliability] err=%s", e)
        return _err_resp("failed to query scraper reliability", request, 500, "Data")


# ── Demand Intelligence ─────────────────────────────────────────────────


@router.get(
    "/demand/{market}",
    summary="Demand signals for a market",
)
async def demand_api(market: str, request: Request):
    from intelligence.demand_intel import DemandIntel
    di = DemandIntel(caller="api")
    ds = di.get_signals(market)
    return {
        "market": ds.market, "market_found": ds.market_found,
        "collected_at": ds.collected_at, "avg_listing_psf": ds.avg_listing_psf,
        "median_listing_psf": ds.median_listing_psf, "listing_trend_30d_pct": ds.listing_trend_30d_pct,
        "listing_count_30d": ds.listing_count_30d, "absorption_pct": ds.absorption_pct,
        "months_of_supply": ds.months_of_supply, "demand_signal": ds.demand_signal,
        "demand_score": ds.demand_score, "demand_score_v2": ds.demand_score_v2,
        "ticket_size_median_cr": ds.ticket_size_median_cr, "days_on_market_p50": ds.days_on_market_p50,
        "config_absorption": ds.config_absorption, "absorption_trend": ds.absorption_trend,
        "days_on_market_by_config": ds.days_on_market_by_config,
        "avg_news_sentiment": ds.avg_news_sentiment,
        "kaveri_monthly_approvals": ds.kaveri_monthly_approvals,
        "signals": ds.signals,
    }


@router.get("/demand", summary="Demand Intelligence dashboard panel")
def demand_panel(request: Request):
    return templates.TemplateResponse(request, "demand_intelligence.html")


# ── Memory Panel ────────────────────────────────────────────────────────


@router.get("/memory", tags=["Memory"], summary="Agent Memory Explorer dashboard panel")
def memory_explorer_panel(request: Request):
    return templates.TemplateResponse(request, "memory_explorer.html")


# ── Data Quality Panel ──────────────────────────────────────────────────


@router.get("/data-quality", tags=["Data Quality"], summary="Data Quality dashboard panel")
def data_quality_panel(request: Request):
    return templates.TemplateResponse(request, "data_quality.html")


# ── Market Forecaster / Spread / Supply ─────────────────────────────────


@router.get(
    "/market/forecast/{market}",
    summary="PSF forecast for a market (3/6/12-month horizons)",
)
@limiter.limit("30/hour")
async def market_forecast(market: str, request: Request = None):
    from utils.psf_forecaster import PSFForecaster
    from config.settings import TARGET_MARKETS as _VALID_MARKETS
    market = (market or "").strip()
    if not market:
        return _err_resp("market is required", request, 400, "Data")
    valid = [m.strip().lower() for m in _VALID_MARKETS]
    if market.lower() not in valid:
        return _err_resp(f"Unknown market '{market}'. Valid: {sorted(set(m.strip() for m in _VALID_MARKETS))}", request, 400, "Data")
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT horizon_months, current_psf, forecast_psf,
                           conf_low, conf_high, trend_direction,
                           slope_pct_per_month, data_points, mae_pct,
                           model_version, forecast_date
                    FROM market_forecasts
                    WHERE market ILIKE :market
                    ORDER BY forecast_date DESC, horizon_months
                    LIMIT 3
                """),
                {"market": f"%{market}%"},
            ).fetchall()
        if rows:
            best = rows[0]
            resp = {
                "market": market, "as_of": str(best.forecast_date) if best.forecast_date else "",
                "trend_direction": best.trend_direction or "unknown",
                "current_psf": float(best.current_psf) if best.current_psf else 0,
                "slope_pct_per_month": float(best.slope_pct_per_month) if best.slope_pct_per_month else 0,
                "data_points": best.data_points or 0, "mae_pct": float(best.mae_pct) if best.mae_pct else 0,
                "model_version": best.model_version or "linear_v1",
            }
            for r in rows:
                h = int(r.horizon_months)
                resp[f"forecast_{h}m"] = float(r.forecast_psf) if r.forecast_psf else 0
                resp[f"conf_low_{h}m"] = float(r.conf_low) if r.conf_low else 0
                resp[f"conf_high_{h}m"] = float(r.conf_high) if r.conf_high else 0
            etag = compute_etag(resp)
            _check = check_etag(request, etag)
            if _check:
                return _check
            return JSONResponse(content=resp, headers={"ETag": f'"{etag}"'})
        fallback = PSFForecaster().forecast(market)
        fallback_data = {
            "market": fallback.market, "as_of": fallback.as_of,
            "trend_direction": fallback.trend_direction, "current_psf": fallback.current_psf,
            "forecast_3m": fallback.forecast_3m, "forecast_6m": fallback.forecast_6m,
            "forecast_12m": fallback.forecast_12m,
            "conf_low_3m": fallback.conf_low_3m, "conf_high_3m": fallback.conf_high_3m,
            "conf_low_6m": fallback.conf_low_6m, "conf_high_6m": fallback.conf_high_6m,
            "conf_low_12m": fallback.conf_low_12m, "conf_high_12m": fallback.conf_high_12m,
            "mae_pct": fallback.mae_pct, "data_points": fallback.data_points,
            "model_version": fallback.model_version,
        }
        etag = compute_etag(fallback_data)
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(content=fallback_data, headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        logger.warning("[API] /market/forecast/%s failed: %s", market, exc)
        return _err_resp(str(exc), request, 500, "Data")


@router.get(
    "/market/spread/{market}",
    summary="Registered-vs-ask PSF spread for a market",
)
@limiter.limit("60/hour")
async def market_spread(market: str, request: Request = None, window_days: int = 180):
    from utils.psf_truth import compute_psf_spread
    from config.settings import TARGET_MARKETS as _VALID_MARKETS
    market = (market or "").strip()
    if not market:
        return _err_resp("market is required", request, 400, "Data")
    valid = [m.strip().lower() for m in _VALID_MARKETS]
    if market.lower() not in valid:
        return _err_resp(f"Unknown market '{market}'. Valid: {sorted(set(m.strip() for m in _VALID_MARKETS))}", request, 400, "Data")
    try:
        window_days = max(30, min(window_days, 365))
        result = compute_psf_spread(market, window_days=window_days)
        spread_data = result.to_dict() if hasattr(result, "to_dict") else result
        etag = compute_etag(spread_data)
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(content=spread_data, headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        logger.warning("[API] /market/spread/{} failed: {}", market, exc)
        return _err_resp(str(exc), request, 500, "Data")


# ── Market Supply (pipeline) ────────────────────────────────────────────


@router.get("/market/supply", summary="Pipeline supply for a market")
async def market_supply(
    request: Request,
    market: str = Query("Yelahanka", description="Market name"),
):
    market = (market or "").strip()
    if not market:
        return _err_resp("market is required", request, 400, "Data")
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT project_name, developer_name, estimated_units,
                           estimated_acres, source, approval_date,
                           expected_completion_year, raw_snippet, created_at
                    FROM supply_pipeline
                    WHERE market ILIKE :market
                    ORDER BY created_at DESC, estimated_units DESC
                    LIMIT 100
                """),
                {"market": f"%{market}%"},
            ).fetchall()
            total = conn.execute(
                _sa_text("SELECT COALESCE(SUM(estimated_units), 0) FROM supply_pipeline WHERE market ILIKE :market"),
                {"market": f"%{market}%"},
            ).scalar() or 0
        records = []
        for row in rows:
            records.append({
                "project_name": row.project_name, "developer_name": row.developer_name,
                "estimated_units": int(row.estimated_units or 0),
                "estimated_acres": float(row.estimated_acres) if row.estimated_acres else None,
                "source": row.source, "approval_date": str(row.approval_date) if row.approval_date else None,
                "expected_completion_year": row.expected_completion_year,
                "raw_snippet": row.raw_snippet,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
        return {"market": market, "total_pipeline_units": int(total), "count": len(records), "records": records}
    except Exception as exc:
        logger.warning("[API] /market/supply failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


# ── Distress Signals ────────────────────────────────────────────────────


@router.get("/distress/signals")
async def distress_signals(
    request: Request,
    market: str = Query("Yelahanka", description="Market name"),
    limit: int = Query(50, ge=1, le=200),
):
    market = (market or "").strip()
    if not market:
        return _err_resp("market is required", request, 400, "Data")
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT developer_name, market, signal_type, stall_count, stall_ratio,
                           mention_count, distress_score, detected_at
                    FROM developer_distress_signals
                    WHERE market = :market
                    ORDER BY detected_at DESC, distress_score DESC, developer_name ASC
                    LIMIT :limit
                """),
                {"market": market, "limit": limit},
            ).fetchall()
        return {
            "market": market, "count": len(rows),
            "signals": [
                {
                    "developer_name": row.developer_name, "market": row.market,
                    "signal_type": row.signal_type, "stall_count": int(row.stall_count or 0),
                    "stall_ratio": float(row.stall_ratio or 0.0), "mention_count": int(row.mention_count or 0),
                    "distress_score": float(row.distress_score or 0.0),
                    "detected_at": row.detected_at.isoformat() if row.detected_at else None,
                }
                for row in rows
            ],
        }
    except Exception as exc:
        logger.warning("[API] /distress/signals failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


# ── Parcel Dossier ──────────────────────────────────────────────────────


@router.get(
    "/parcel/{village}/{survey_no}",
    summary="Full parcel dossier with deed history, RERA projects, comps",
)
@limiter.limit("60/hour")
async def parcel_dossier(village: str, survey_no: str, request: Request = None):
    from urllib.parse import unquote
    from decimal import Decimal
    village = unquote(village)
    survey_no = unquote(survey_no)
    if not village or not survey_no:
        return _err_resp("village and survey_no are required", request, 400, "Data")
    try:
        with _get_sa_engine().connect() as conn:
            parcel = conn.execute(
                _sa_text("""
                    SELECT id, village, survey_no, district, taluk, hobli, extent_sqft, source
                    FROM parcels WHERE village = :v AND survey_no = :s LIMIT 1
                """),
                {"v": village, "s": survey_no},
            ).fetchone()
            if not parcel:
                return _err_resp("Parcel not found", request, 404, "Data")
            parcel_dict = dict(parcel._mapping)
            parcel_id = parcel_dict["id"]
            deed_rows = conn.execute(
                _sa_text("""
                    SELECT id, doc_no, reg_date, sro, survey_no, extent_sqft,
                           consideration_inr, psf, deed_type, buyer_name_raw,
                           seller_name_raw, data_source
                    FROM registered_transactions WHERE parcel_id = :pid
                    ORDER BY reg_date DESC LIMIT 50
                """),
                {"pid": parcel_id},
            ).fetchall()
            deed_history = [dict(r._mapping) for r in deed_rows]
            rera_rows = conn.execute(
                _sa_text("""
                    SELECT rp.id, rp.rera_number, rp.project_name,
                           d.name AS developer_name, rp.survey_no,
                           rp.project_status, rp.total_units
                    FROM rera_projects rp
                    LEFT JOIN developers d ON d.id = rp.developer_id
                    WHERE rp.parcel_id = :pid
                    ORDER BY rp.created_at DESC LIMIT 20
                """),
                {"pid": parcel_id},
            ).fetchall()
            rera_projects = [dict(r._mapping) for r in rera_rows]
            gv_row = conn.execute(
                _sa_text("""
                    SELECT gv.guidance_value_psf AS guidance_value, gv.data_source AS source,
                           gv.effective_from AS gv_date, gv.area_code AS zone_code
                    FROM guidance_values gv
                    WHERE gv.locality ILIKE '%' || :v || '%'
                    ORDER BY gv.effective_from DESC NULLS LAST LIMIT 1
                """),
                {"v": village},
            ).fetchone()
            guidance_value = dict(gv_row._mapping) if gv_row else None
            assembly_rows = conn.execute(
                _sa_text("""
                    SELECT id, buyer_name_norm, parcel_count, total_extent_sqft,
                           first_deed_date, last_deed_date, confidence
                    FROM assembly_signals WHERE village = :v AND status = 'open'
                    ORDER BY parcel_count DESC LIMIT 10
                """),
                {"v": village},
            ).fetchall()
            assembly_flags = [dict(r._mapping) for r in assembly_rows]
            comps_row = conn.execute(
                _sa_text("""
                    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rt.psf) AS median_psf,
                           COUNT(*) AS n
                    FROM registered_transactions rt
                    WHERE rt.village = :v AND rt.psf IS NOT NULL
                      AND rt.psf > 500 AND rt.psf < 50000
                      AND rt.reg_date >= NOW() - INTERVAL '12 months'
                """),
                {"v": village},
            ).fetchone()
            comps = None
            if comps_row:
                md = dict(comps_row._mapping)
                comps = {"median_psf": float(md["median_psf"]) if md.get("median_psf") else None,
                         "n": md.get("n", 0) or 0, "window": "12mo", "scope": "same village"}
        zone_risk = None
        try:
            from utils.zone_risk_checker import check_zone_risk
            zr = check_zone_risk(village, zone="R2")
            zone_risk = {
                "market": zr.market, "zone": zr.zone, "far": zr.far,
                "max_height_m": zr.max_height_m, "ground_coverage_pct": zr.ground_coverage_pct,
                "risk_level": zr.risk_level, "overlay_risks": zr.overlay_risks,
            }
        except Exception:
            pass

        def _serialize(val):
            if val is None:
                return val
            if isinstance(val, Decimal):
                return float(val)
            if hasattr(val, "isoformat"):
                return val.isoformat()
            if isinstance(val, (float, int)):
                return val
            return str(val)

        result = {
            "parcel": {k: _serialize(v) for k, v in parcel_dict.items()},
            "deed_history": [{k: _serialize(v) for k, v in d.items()} for d in deed_history],
            "rera_projects": [{k: _serialize(v) for k, v in r.items()} for r in rera_projects],
            "guidance_value": {k: _serialize(v) for k, v in guidance_value.items()} if guidance_value else None,
            "zone_risk": zone_risk,
            "assembly_flags": [{k: _serialize(v) for k, v in a.items()} for a in assembly_flags],
            "comps": comps,
        }
        return JSONResponse(result)
    except Exception as exc:
        logger.error("[API] /parcel/%s/%s failed: %s", village, survey_no, exc)
        return _err_resp(str(exc), None, 500, "Data")


_OWNERSHIP_CACHE: dict[str, tuple[float, dict]] = {}
_OWNERSHIP_CACHE_TTL = 300
_OWNERSHIP_CACHE_MAX = 100

_SURVEY_NO_PATTERN = re.compile(r"^[\w]+/[\w\-]+$")


@router.get(
    "/parcel/ownership",
    response_model=OwnershipChainResponse,
    summary="Ownership chain for a survey number (RTC/Bhoomi)",
)
@limiter.limit("60/hour")
async def parcel_ownership(
    request: Request,
    survey_no: str = Query(..., min_length=3, max_length=50,
                           description="Survey number (e.g. 45/2)"),
    market: str = Query(default="Yelahanka", min_length=2, max_length=100,
                        description="Market name"),
):
    if not _SURVEY_NO_PATTERN.match(survey_no):
        return _err_resp("Invalid survey_no format — expected format like '45/2' or '101/1A'", request, 422, "Data")
    cache_key = f"{market}:{survey_no}"
    cached = _OWNERSHIP_CACHE.get(cache_key)
    if cached is not None:
        if time.time() < cached[0]:
            return cached[1]
    try:
        with _get_sa_engine().connect() as conn:
            row = conn.execute(
                _sa_text("""
                    SELECT poc.survey_no, poc.market, poc.khata_no, poc.owner_name,
                           poc.previous_owner, poc.transfer_date, poc.area_acres,
                           poc.govt_acquisition_notice, poc.encumbrance_flag,
                           poc.fetched_at, poc.parcel_id, poc.parser_completeness_score
                    FROM parcel_ownership_chain poc
                    WHERE poc.survey_no = :sno AND poc.market = :mkt
                    ORDER BY poc.fetched_at DESC LIMIT 1
                """),
                {"sno": survey_no, "mkt": market},
            ).fetchone()
        if not row:
            return _err_resp("No ownership chain found for this survey_no/market", request, 404, "Data")
        result = {
            "survey_no": row.survey_no,
            "market": row.market,
            "khata_no": row.khata_no,
            "owner_name": row.owner_name,
            "previous_owner": row.previous_owner,
            "transfer_date": row.transfer_date.isoformat() if row.transfer_date else None,
            "area_acres": float(row.area_acres) if row.area_acres is not None else None,
            "govt_acquisition_notice": bool(row.govt_acquisition_notice),
            "encumbrance_flag": bool(row.encumbrance_flag),
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            "parcel_id": str(row.parcel_id) if row.parcel_id else None,
            "parser_completeness_score": float(row.parser_completeness_score)
                if row.parser_completeness_score is not None else None,
        }
        if len(_OWNERSHIP_CACHE) > _OWNERSHIP_CACHE_MAX:
            _OWNERSHIP_CACHE.clear()
        _OWNERSHIP_CACHE[cache_key] = (time.time() + _OWNERSHIP_CACHE_TTL, result)
        return result
    except Exception as exc:
        logger.error("[API] /parcel/ownership failed: %s", exc)
        return _err_resp("Failed to query ownership chain — please try again later", request, 500, "Data")


@router.get("/parcel/villages", summary="Distinct villages with parcel data")
@limiter.limit("120/minute")
async def parcel_villages(request: Request = None):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(_sa_text("SELECT DISTINCT village FROM parcels ORDER BY village")).fetchall()
            villages = [r[0] for r in rows if r[0]]
            return {"villages": villages if villages else []}
    except Exception as exc:
        logger.error("[API] /parcel/villages failed: %s", exc)
        return JSONResponse({"villages": []})


@router.get("/parcel", response_class=HTMLResponse, summary="Parcel lookup dashboard panel")
async def parcel_panel(request: Request):
    return templates.TemplateResponse(request, "parcel.html")


# ── Corridor Scorer v2 ──────────────────────────────────────────────────


class CorridorBoundaryFeature(BaseModel):
    type: str = "Feature"
    geometry: dict | None = None
    properties: dict = {}


class CorridorScoreResponse(BaseModel):
    corridor_id: str
    corridor_name: str
    composite: float
    velocity_score: float
    psf_trend_score: float
    gcc_score: float
    infra_score: float
    n_transactions: int = 0
    avg_psf: float | None = None
    psf_mom: float | None = None
    data_window: str = ""
    notes: list[str] = []
    boundary_geojson: dict | None = None


class CorridorScoreListResponse(BaseModel):
    corridors: list[CorridorScoreResponse]
    as_of: str
    window_months: int
    market: str | None = None


@router.get(
    "/corridor/score",
    response_model=CorridorScoreListResponse,
    response_model_exclude_none=True,
    summary="Corridor scores using PostGIS spatial join (v2). "
            "Optional ?geojson=true includes boundary polygons. "
            "In _READ_ONLY_PATHS — no auth required. "
            "Rate limited 60/hour.",
    responses={
        200: {"description": "Corridor scores with optional GeoJSON boundaries"},
        400: {"description": "Invalid query parameters"},
        500: {"description": "Scoring engine error"},
    },
)
@limiter.limit("60/hour")
async def corridor_score(
    request: Request,
    geojson: bool = Query(default=False, description="Include boundary GeoJSON"),
    window_months: int = Query(default=3, ge=1, le=24, description="Lookback window in months"),
    market: str | None = Query(default=None, description="Optional market filter (exact match)"),
):
    import uuid as _uuid
    _trace_id = str(_uuid.uuid4())[:8]
    from utils.corridor_scorer_v2 import CorridorScorerV2, CORRIDOR_DEFINITIONS
    try:
        window_months = max(1, min(window_months, 24))
        scorer = CorridorScorerV2()
        scores = scorer.score_all(window_months=window_months, as_geojson=geojson)

        if market:
            market_lower = market.strip().lower()
            scores = [
                s for s in scores
                if any(
                    c.get("market", "").lower() == market_lower
                    for c in CORRIDOR_DEFINITIONS
                    if c["id"] == s.corridor_id
                )
            ]

        result = {
            "corridors": [s.to_dict() for s in scores],
            "as_of": datetime.now(timezone.utc).isoformat(),
            "window_months": window_months,
            "market": market.strip() if market else None,
        }
        return JSONResponse(
            content=result,
            headers={
                "Cache-Control": "private, max-age=30",
                "X-Trace-ID": _trace_id,
            },
        )
    except Exception as exc:
        logger.error("[API] /corridor/score trace=%s failed: %s", _trace_id, exc)
        return JSONResponse(
            {"error": "Corridor scoring engine unavailable", "detail": str(exc), "trace_id": _trace_id},
            status_code=500,
        )


# ── Competitive Intelligence ────────────────────────────────────────────


@router.get(
    "/competitive/pulse",
    summary="Competitive pulse — new launches, PSF movers, absorption leaders",
)
@limiter.limit("20/hour")
async def competitive_pulse(
    request: Request,
    market: str | None = Query(default=None, description="Market filter"),
    days: int = Query(default=7, ge=1, le=365, description="New launch window days"),
    top_n: int = Query(default=5, ge=1, le=50, description="Absorption leader count"),
):
    import time as _time_now
    safe_market = market or ""
    cache_key = f"{safe_market}:{days}:{top_n}"
    with _pulse_cache_lock:
        cached = _pulse_cache.get(cache_key)
        if cached is not None:
            ts, data = cached
            if _time_now.time() < ts:
                _pulse_cache.move_to_end(cache_key)
                return data
    try:
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        result = engine.pulse(market=market, days=days, top_n=top_n)
        with _pulse_cache_lock:
            _pulse_cache[cache_key] = (_time_now.time() + _PULSE_CACHE_TTL, result)
            if len(_pulse_cache) > _PULSE_CACHE_MAX:
                _pulse_cache.popitem(last=False)
        return result
    except Exception as exc:
        logger.error("[competitive_pulse] %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


# ── Govt/Policy routes ──────────────────────────────────────────────────


@router.get("/govt/events", tags=["Govt/Policy"], summary="List government/infrastructure/policy events")
@limiter.limit("30/minute")
async def govt_events(
    request: Request,
    market: str | None = Query(None), category: str | None = Query(None),
    signal: str | None = Query(None), limit: int = Query(20, ge=1, le=100),
):
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        where_clauses = []
        params = {}
        if category:
            where_clauses.append("category = :category")
            params["category"] = category
        if signal:
            where_clauses.append("signal_strength = :signal")
            params["signal"] = signal
        if market:
            where_clauses.append(":market = ANY(micro_markets)")
            params["market"] = market
        where_sql = " AND ".join(where_clauses)
        if where_sql:
            where_sql = "WHERE " + where_sql
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT id, headline, category, subcategory, location_text,
                           micro_markets, investment_cr, stage, impact_score,
                           signal_strength, time_horizon, actionability,
                           summary, why_it_matters, source_urls,
                           published_date, is_north_bengaluru, scraped_at
                    FROM govt_policy_events {where_sql}
                    ORDER BY impact_score DESC NULLS LAST, scraped_at DESC
                    LIMIT :lim
                """),
                {**params, "lim": limit},
            ).fetchall()
        nb_count = sum(1 for r in rows if r[16])
        events = []
        for r in rows:
            events.append({
                "id": r[0], "headline": r[1], "category": r[2], "subcategory": r[3],
                "location_text": r[4], "micro_markets": r[5] or [],
                "investment_cr": float(r[6]) if r[6] else None, "stage": r[7],
                "impact_score": r[8], "signal_strength": r[9], "time_horizon": r[10],
                "actionability": r[11], "summary": r[12], "why_it_matters": r[13],
                "source_urls": r[14] or [], "published_date": str(r[15]) if r[15] else None,
                "is_north_bengaluru": bool(r[16]), "scraped_at": str(r[17]) if r[17] else None,
            })
        return JSONResponse({"events": events, "total": len(events), "north_bengaluru_count": nb_count})
    except Exception as exc:
        logger.warning("[API] /govt/events failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


@router.get("/govt/north-score", tags=["Govt/Policy"], summary="North Bengaluru govt/infra/policy pipeline score")
@limiter.limit("30/minute")
async def govt_north_score(request: Request):
    try:
        from intelligence.govt_policy_intel import GovtPolicyIntel
        intel = GovtPolicyIntel(caller="api")
        result = intel.compute("north_bengaluru_aggregate")
        return JSONResponse({
            "north_bengaluru_score": result.north_bengaluru_score,
            "high_opportunity_count": result.high_opportunity_count,
            "risk_count": result.risk_count,
            "top_infra_events": result.top_infra_events,
            "top_policy_events": result.top_policy_events,
            "computed_at": result.computed_at,
        })
    except Exception as exc:
        logger.warning("[API] /govt/north-score failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


@router.get("/govt/digest", tags=["Govt/Policy"], summary="Weekly govt/policy digest for North Bengaluru")
@limiter.limit("30/minute")
async def govt_digest(request: Request):
    try:
        from intelligence.govt_policy_intel import GovtPolicyIntel
        intel = GovtPolicyIntel(caller="api")
        result = intel.compute("north_bengaluru_aggregate")
        return JSONResponse({"digest": result.weekly_digest, "computed_at": result.computed_at})
    except Exception as exc:
        logger.warning("[API] /govt/digest failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


@router.get("/govt", tags=["Govt/Policy"], summary="Govt/Policy dashboard page")
@limiter.limit("20/minute")
async def govt_policy_panel(request: Request):
    try:
        return templates.TemplateResponse(request, "govt_policy.html")
    except Exception as exc:
        logger.error("[govt_policy_panel] %s", exc)
        return _err_resp("template not found", request, 500, "Data")


# ── GCC routes ──────────────────────────────────────────────────────────


@router.get("/gcc/events")
async def gcc_events(
    request: Request,
    market: str | None = Query(None, description="Filter by market"),
    corridor: str | None = Query(None, description="Filter by corridor slug"),
    maturity: str | None = Query(None, description="Comma-separated maturity levels"),
    include_negative: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        from intelligence.gcc_intel import GCCIntel
        maturity_levels = None
        if maturity:
            try:
                maturity_levels = [int(x.strip()) for x in maturity.split(",") if x.strip()]
            except ValueError:
                return _err_resp("maturity must be comma-separated integers", request, 400, "Data")
        corridors = None
        if corridor:
            corridors = [c.strip() for c in corridor.split(",") if c.strip()]
        intel = GCCIntel()
        events = intel.get_events(
            market=market, corridors=corridors, maturity_levels=maturity_levels,
            include_negative=include_negative, limit=limit, offset=offset,
        )
        north_scores = {}
        for mkt in ("Yelahanka", "Devanahalli", "Hebbal"):
            try:
                r = intel.get_gcc_score(mkt)
                north_scores[mkt] = r.gcc_north_norm
            except Exception:
                pass
        return JSONResponse({
            "events": [
                {
                    "id": e.id, "canonical_id": e.canonical_id,
                    "company": e.company, "sector": e.sector,
                    "country_of_origin": e.country_of_origin,
                    "bengaluru_location": e.bengaluru_location,
                    "nearest_corridor": e.nearest_corridor, "entrant_type": e.entrant_type,
                    "work_model": e.work_model,
                    "signal_maturity_level": e.signal_maturity_level,
                    "is_negative_signal": e.is_negative_signal,
                    "north_bengaluru_impact_score": e.north_bengaluru_impact_score,
                    "planned_headcount": e.planned_headcount,
                    "median_ctc_l": e.median_ctc_l, "gcc_signal_score": e.gcc_signal_score,
                    "primary_housing_segment": e.primary_housing_segment,
                    "time_horizon": e.time_horizon,
                    "estimated_demand_units": e.estimated_demand_units,
                    "source_name": e.source_name, "source_reliability": e.source_reliability,
                    "announced_at": str(e.announced_at) if e.announced_at else None,
                    "discord_alert_fired": e.discord_alert_fired,
                }
                for e in events
            ],
            "total": len(events),
            "gcc_north_norm": north_scores,
        })
    except Exception as exc:
        logger.warning("[API] /gcc/events failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


@router.get("/gcc/north-score")
async def gcc_north_score(request: Request):
    try:
        from intelligence.gcc_intel import GCCIntel
        intel = GCCIntel()
        result = {}
        for mkt in ("Yelahanka", "Devanahalli", "Hebbal"):
            r = intel.get_gcc_score(mkt)
            result[mkt] = {
                "gcc_north_norm": r.gcc_north_norm, "corridor": r.corridor,
                "event_count_12m": r.event_count_12m, "event_count_90d": r.event_count_90d,
                "total_headcount_12m": r.total_headcount_12m,
                "avg_gcc_signal_score": r.avg_gcc_signal_score,
                "top_sectors": r.top_sectors,
                "dominant_housing_segment": r.dominant_housing_segment,
                "has_level1_signal": r.has_level1_signal,
                "negative_suppressor_applied": r.negative_suppressor_applied,
                "signals": r.signals, "collected_at": r.collected_at,
            }
        return JSONResponse(result)
    except Exception as exc:
        logger.warning("[API] /gcc/north-score failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


@router.post("/gcc/events")
async def gcc_create_event(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not body.get("company") or not body.get("bengaluru_location"):
        return _err_resp("company and bengaluru_location are required", request, 400, "Data")
    try:
        from ingest.plugins.gcc_plugin import _make_canonical_id, _resolve_corridor, _compute_gcc_score
        from utils.db import get_engine
        from sqlalchemy import text as _t
        announced = body.get("announced_at") or str(__import__("datetime").date.today())
        cid = _make_canonical_id(body["company"], body.get("bengaluru_location", "Bengaluru"), announced)
        corridor, nb_impact = _resolve_corridor(body.get("bengaluru_location", ""))
        if not body.get("nearest_corridor"):
            body["nearest_corridor"] = corridor
        if body.get("north_bengaluru_impact_score") is None:
            body["north_bengaluru_impact_score"] = nb_impact
        gcc_score = _compute_gcc_score(body)
        with get_engine().begin() as conn:
            conn.execute(
                _t("""
                INSERT INTO gcc_events (
                    canonical_id, company, sector, country_of_origin,
                    bengaluru_location, nearest_corridor, entrant_type,
                    work_model, signal_maturity_level, is_negative_signal,
                    north_bengaluru_impact_score, investment_cr,
                    planned_headcount, headcount_timeline_months,
                    median_ctc_l, office_sqft,
                    demand_creation_score, residential_impact_score,
                    appreciation_impact_score, rental_impact_score,
                    gcc_signal_score, primary_housing_segment,
                    time_horizon, source_name, source_reliability,
                    announced_at, discord_alert_fired
                ) VALUES (
                    :canonical_id, :company, :sector, :country_of_origin,
                    :bengaluru_location, :nearest_corridor, :entrant_type,
                    :work_model, :signal_maturity_level, :is_negative_signal,
                    :nb_impact, :investment_cr,
                    :planned_headcount, :headcount_timeline_months,
                    :median_ctc_l, :office_sqft,
                    :demand_creation_score, :residential_impact_score,
                    :appreciation_impact_score, :rental_impact_score,
                    :gcc_signal_score, :primary_housing_segment,
                    :time_horizon, :source_name, :source_reliability,
                    CAST(:announced_at AS date), FALSE
                ) ON CONFLICT (canonical_id) DO NOTHING
            """),
                {
                    "canonical_id": cid, "company": body["company"],
                    "sector": body.get("sector"), "country_of_origin": body.get("country_of_origin"),
                    "bengaluru_location": body.get("bengaluru_location"),
                    "nearest_corridor": body.get("nearest_corridor"),
                    "entrant_type": body.get("entrant_type", "EXPANSION"),
                    "work_model": body.get("work_model", "HYBRID"),
                    "signal_maturity_level": body.get("signal_maturity_level", 3),
                    "is_negative_signal": bool(body.get("is_negative_signal", False)),
                    "nb_impact": body["north_bengaluru_impact_score"],
                    "investment_cr": body.get("investment_cr"),
                    "planned_headcount": body.get("planned_headcount"),
                    "headcount_timeline_months": body.get("headcount_timeline_months"),
                    "median_ctc_l": body.get("median_ctc_l"),
                    "office_sqft": body.get("office_sqft"),
                    "demand_creation_score": body.get("demand_creation_score"),
                    "residential_impact_score": body.get("residential_impact_score"),
                    "appreciation_impact_score": body.get("appreciation_impact_score"),
                    "rental_impact_score": body.get("rental_impact_score"),
                    "gcc_signal_score": gcc_score,
                    "primary_housing_segment": body.get("primary_housing_segment"),
                    "time_horizon": body.get("time_horizon"),
                    "source_name": body.get("source_name"),
                    "source_reliability": body.get("source_reliability", "PRESS"),
                    "announced_at": announced,
                },
            )
        from intelligence.gcc_intel import GCCIntel
        for mkt in ("Yelahanka", "Devanahalli", "Hebbal"):
            GCCIntel().invalidate_cache(mkt)
        return JSONResponse({"canonical_id": cid, "gcc_signal_score": gcc_score}, status_code=201)
    except Exception as exc:
        logger.warning("[API] POST /gcc/events failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


# ── Finance CashFlow ────────────────────────────────────────────────────


class CashFlowRowResponse(BaseModel):
    month: int
    construction_outflow_cr: float
    interest_payment_cr: float
    brokerage_charge_cr: float
    sales_inflow_cr: float
    cumulative_cash_position_cr: float


class CashFlowSummaryResponse(BaseModel):
    peak_negative_cr: float
    breakeven_month: int | None = None
    roi_annualized_pct: float | None = None
    irr_npv_pct: float | None = None


class CashFlowResponse(BaseModel):
    schedule: list[CashFlowRowResponse]
    summary: CashFlowSummaryResponse


@router.get(
    "/finance/cashflow",
    summary="Monthly cash-flow projection with debt service and brokerage",
    response_model=CashFlowResponse,
)
@limiter.limit("30/hour")
async def finance_cashflow(
    request: Request,
    land_cost_cr: float = Query(..., description="Land acquisition cost in Cr"),
    gdc_cr: float = Query(..., description="Gross development cost in Cr"),
    construction_cost_cr: float = Query(..., description="Construction cost in Cr"),
    loan_pct: float = Query(default=0.5, ge=0.0, le=1.0, description="Loan-to-land-cost ratio"),
    months: int = Query(default=36, ge=1, le=120, description="Project timeline in months (1-120)"),
):
    from utils.irr_model import build_cash_flow
    try:
        months = max(1, min(months, 120))
        with db_query_duration_seconds.labels(query_name="build_cash_flow").time():
            result = build_cash_flow(
                land_cost_cr=land_cost_cr,
                gdc_cr=gdc_cr,
                construction_cost_cr=construction_cost_cr,
                loan_pct=loan_pct,
                months=months,
            )
        response = CashFlowResponse(
            schedule=[
                CashFlowRowResponse(**r.__dict__) for r in result.schedule
            ],
            summary=CashFlowSummaryResponse(**result.summary.__dict__),
        )
        return JSONResponse(
            content=response.model_dump(),
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        logger.error("[finance_cashflow] %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


# ── Demand Config Split ─────────────────────────────────────────────────


@router.get(
    "/demand/config-split",
    summary="Demand absorption split by bedroom configuration",
)
@limiter.limit("30/hour")
async def demand_config_split(
    request: Request,
    market: str = Query(default="Yelahanka", description="Market name"),
):
    from intelligence.demand_intel import DemandIntel
    try:
        with db_query_duration_seconds.labels(query_name="demand_config_split").time():
            di = DemandIntel(caller="api")
            split = di.get_config_absorption(market)
        return JSONResponse(
            content={"market": market, "absorption_by_config": split},
            headers={"Cache-Control": "max-age=300"},
        )
    except Exception as exc:
        logger.error("[demand_config_split] %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


# ── Deed Throughput (GATE-136, T-1368) ──────────────────────────────────


_deed_throughput_total = _counter(
    "deed_throughput_total", "Deed throughput queries by market and status", ["market", "status"],
)


class DeedThroughputWeek(BaseModel):
    week_start: str | None = None
    deed_count: int = 0
    market: str = "Unknown"


class DeedThroughputResponse(BaseModel):
    weeks: list[DeedThroughputWeek]
    current_week_count: int = 0
    target: int = 50
    status: str = "critical"


@router.get(
    "/deeds/throughput",
    summary="Weekly deed throughput per market — last 12 weeks",
    description="Returns weekly Sale deed counts per market for the last 12 weeks. "
                "Status thresholds: 0=critical (no data), <50=at_risk (below target), "
                ">=50=on_track (target met). The 50/week target is the GATE-118 "
                "kill-criteria deadline (2026-08-15). The separate Discord alert "
                "fires at <20/week as earlier warning.",
    tags=["Deeds"],
)
@limiter.limit("30/minute")
async def deeds_throughput(
    request: Request,
    market: str = Query(default=None, description="Optional market filter (Yelahanka, Devanahalli, Hebbal)"),
):
    mkt_param = market.strip() if market else None
    try:
        with db_query_duration_seconds.labels(query_name="deed_throughput").time():
            with _get_sa_engine().connect() as conn:
                base_sql = """
                    SELECT t.market, t.week_start, t.current_week_count
                    FROM v_deed_throughput_weekly t
                """
                params: dict[str, object] = {}
                if mkt_param:
                    base_sql += " WHERE t.market ILIKE :mkt"
                    params["mkt"] = f"%{mkt_param}%"
                base_sql += " ORDER BY t.week_start DESC LIMIT 12"
                rows = conn.execute(
                    _sa_text(base_sql),
                    params,
                ).fetchall()
        weeks = [
            DeedThroughputWeek(
                week_start=str(r[1]) if r[1] else None,
                deed_count=int(r[2]) if r[2] else 0,
                market=str(r[0]) if r[0] else "Unknown",
            )
            for r in rows
        ]
        current_count = weeks[0].deed_count if weeks else 0
        if current_count == 0:
            status = "critical"
        elif current_count < 50:
            status = "at_risk"
        else:
            status = "on_track"
        _deed_throughput_total.labels(market=mkt_param or "all", status=status).inc()
        return DeedThroughputResponse(
            weeks=weeks,
            current_week_count=current_count,
            target=50,
            status=status,
        )
    except Exception as exc:
        logger.error("[deeds_throughput] %s", exc)
        _deed_throughput_total.labels(market=mkt_param or "all", status="error").inc()
        return _err_resp("failed to query deed throughput", request, 500, "Data")


# ── Decision Journal (GATE-137) ──────────────────────────────────────────


@router.get(
    "/decision-journal",
    summary="List decision journal entries",
    tags=["Decision Journal"],
)
@limiter.limit("30/minute")
async def decision_journal_list(
    request: Request,
    market: str = Query(default=None, description="Optional market filter"),
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        from utils.decision_journal import list_entries
        entries = list_entries(market=market, limit=limit)
        return {"entries": entries, "count": len(entries)}
    except Exception as exc:
        logger.warning("[decision_journal_list] %s", exc)
        return _err_resp("failed to query decision journal", request, 500, "Data")


@router.get(
    "/decision-journal/{entry_id}",
    summary="Get a single decision journal entry",
    tags=["Decision Journal"],
)
@limiter.limit("30/minute")
async def decision_journal_get(request: Request, entry_id: int):
    try:
        from utils.decision_journal import get_entry
        entry = get_entry(entry_id)
        if not entry:
            return _err_resp("entry not found", request, 404, "Decision Journal")
        return entry
    except Exception as exc:
        logger.warning("[decision_journal_get] %s", exc)
        return _err_resp("failed to query decision journal", request, 500, "Data")


# ── Assembly Alerts (GATE-140) ──────────────────────────────────────────


@router.get(
    "/intel/assembly-alerts",
    summary="Active assembly detection signals, sorted by confidence",
    tags=["Assembly"],
)
@limiter.limit("30/minute")
async def assembly_alerts(
    request: Request,
    market: str = Query(default=None, description="Market filter (optional)"),
    min_confidence: float = Query(default=0.5, ge=0.0, le=1.0, description="Minimum confidence threshold"),
):
    try:
        with _get_sa_engine().connect() as conn:
            where = ["s.status = 'open'"]
            params: dict[str, object] = {}
            if market:
                mkt = _normalize_market(market)
                if mkt:
                    where.append("s.market ILIKE :mkt")
                    params["mkt"] = f"%{mkt}%"
            where.append(
                "((s.confidence_score IS NOT NULL AND s.confidence_score >= :mc) "
                "OR (s.confidence IS NOT NULL AND s.confidence >= :mc2))"
            )
            params["mc"] = min_confidence
            params["mc2"] = min_confidence
            where_sql = " AND ".join(where)
            rows = conn.execute(
                _sa_text(f"""
                    SELECT s.market, s.village, s.hobli,
                           COALESCE(s.buyer_name, s.buyer_name_norm) AS buyer_name,
                           s.parcel_count,
                           COALESCE(s.total_area_sqm, s.total_extent_sqft / 10.764) AS area_sqm,
                           COALESCE(s.confidence_score, s.confidence) AS confidence_score,
                           s.first_deed_date AS first_txn_date,
                           s.detected_at,
                           s.survey_numbers,
                           CASE
                               WHEN s.detected_at IS NOT NULL
                               THEN EXTRACT(DAY FROM NOW() - s.detected_at)::INTEGER
                               WHEN s.first_deed_date IS NOT NULL
                               THEN EXTRACT(DAY FROM NOW() - s.first_deed_date)::INTEGER
                               ELSE 0
                           END AS days_active
                    FROM assembly_signals s
                    WHERE {where_sql}
                    ORDER BY confidence_score DESC NULLS LAST
                    LIMIT 100
                """),
                params,
            ).fetchall()
        results = []
        for r in rows:
            results.append({
                "market": r.market or "Unknown",
                "village": r.village,
                "hobli": r.hobli or "",
                "buyer_name": r.buyer_name or "",
                "parcel_count": int(r.parcel_count) if r.parcel_count else 0,
                "area_sqm": float(r.area_sqm) if r.area_sqm else 0.0,
                "confidence_score": float(r.confidence_score) if r.confidence_score else 0.0,
                "first_txn_date": str(r.first_txn_date) if r.first_txn_date else None,
                "detected_at": str(r.detected_at) if r.detected_at else None,
                "survey_numbers": r.survey_numbers if r.survey_numbers else [],
                "days_active": int(r.days_active) if r.days_active else 0,
            })
        return {"alerts": results, "count": len(results)}
    except Exception as exc:
        logger.warning("[assembly_alerts] %s", exc)
        return _err_resp("failed to query assembly alerts", request, 500, "Data")


# ── Forecast Accuracy ────────────────────────────────────────────────────


@router.get(
    "/intel/forecast-accuracy",
    summary="PSF forecast accuracy per market (MAPE + last 10 predictions)",
    tags=["Intel"],
)
@limiter.limit("30/minute")
async def forecast_accuracy(
    request: Request,
    market: str = Query(default=None, description="Market filter (optional)"),
):
    """Return per-market MAPE and recent predictions from the prediction ledger.

    Uses a single DB round-trip per market (COUNT + SELECT combined via a
    subquery window) to minimize connection overhead. Empty ledger returns
    mape=null and last_10_predictions=[].
    """
    try:
        from utils.prediction_tracker import compute_mape
        from config.settings import TARGET_MARKETS as _VALID_MARKETS

        markets = [m.strip() for m in _VALID_MARKETS]
        if market:
            canonical = _normalize_market(market)
            if not canonical:
                return _err_resp(f"Unknown market '{market}'. Valid: {sorted(_VALID_MARKETS)}", request, 400, "Data")
            markets = [canonical]

        result = {}
        with _get_sa_engine().connect() as conn:
            for m in markets:
                mape = compute_mape(m)
                stats = conn.execute(
                    _sa_text("""
                        WITH filtered AS (
                            SELECT predicted_psf, actual_psf, error_pct,
                                   predicted_at, measured_at
                            FROM prediction_ledger_psf
                            WHERE market = :market AND actual_psf IS NOT NULL
                        )
                        SELECT (SELECT COUNT(*) FROM filtered) AS sample_count,
                               json_agg(
                                   json_build_object(
                                       'predicted_psf', predicted_psf,
                                       'actual_psf', actual_psf,
                                       'error_pct', error_pct,
                                       'predicted_at', predicted_at,
                                       'measured_at', measured_at
                                   )
                                   ORDER BY predicted_at DESC
                               ) FILTER (WHERE row_number() OVER (ORDER BY predicted_at DESC) <= 10)
                               AS last_10
                        FROM filtered
                    """),
                    {"market": m},
                ).fetchone()

                sample_count = stats[0] if stats and stats[0] else 0
                last_10_raw = stats[1] if stats and stats[1] else []

                last_10 = []
                for entry in last_10_raw:
                    item = {
                        "predicted_psf": float(entry["predicted_psf"]) if entry.get("predicted_psf") else None,
                        "actual_psf": float(entry["actual_psf"]) if entry.get("actual_psf") else None,
                        "error_pct": float(entry["error_pct"]) if entry.get("error_pct") else None,
                        "predicted_at": str(entry["predicted_at"]) if entry.get("predicted_at") else None,
                        "measured_at": str(entry["measured_at"]) if entry.get("measured_at") else None,
                    }
                    last_10.append(item)

                result[m] = {
                    "mape": mape,
                    "sample_count": sample_count,
                    "last_10_predictions": last_10,
                }

        etag = compute_etag(result)
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(content=result, headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        logger.warning("[API] /intel/forecast-accuracy failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Data")


# ── Misc panel pages ────────────────────────────────────────────────────


@router.get("/digest", response_class=HTMLResponse, summary="Intelligence Digest panel")
async def digest_panel(request: Request):
    try:
        return templates.TemplateResponse(request, "digest.html")
    except Exception as exc:
        logger.error("[digest_panel] %s", exc)
        return _err_resp("template not found", request, 500, "Data")


@router.get("/projects", summary="Operations Projects dashboard panel")
def projects_panel(request: Request):
    return templates.TemplateResponse(request, "projects.html")


# ── Investor Brief (GATE-143) ──────────────────────────────────────────

# Prometheus metrics
_investor_brief_requests_total = _counter(
    "investor_brief_requests_total",
    "Investor brief requests by market and status",
    ["market", "status"],
)
_investor_brief_duration_seconds = _histogram(
    "investor_brief_duration_seconds",
    "Investor brief generation duration in seconds",
    ["market"],
    buckets=(1, 2.5, 5, 10, 30, 60, float("inf")),
)
_investor_brief_cache_hits_total = _counter(
    "investor_brief_cache_hits_total",
    "Investor brief cache hits by market",
    ["market"],
)

_INVESTOR_BRIEF_CACHE: dict[str, tuple[str, float]] = {}
_INVESTOR_BRIEF_CACHE_TTL = 300.0
_INVESTOR_BRIEF_CACHE_LOCK = threading.Lock()


def _cached_brief(key: str) -> str | None:
    with _INVESTOR_BRIEF_CACHE_LOCK:
        entry = _INVESTOR_BRIEF_CACHE.get(key)
        if entry and time.time() - entry[1] < _INVESTOR_BRIEF_CACHE_TTL:
            return entry[0]
    return None


def _set_cached_brief(key: str, value: str) -> None:
    with _INVESTOR_BRIEF_CACHE_LOCK:
        _INVESTOR_BRIEF_CACHE[key] = (value, time.time())
        if len(_INVESTOR_BRIEF_CACHE) > 100:
            oldest = min(_INVESTOR_BRIEF_CACHE.items(), key=lambda kv: kv[1][1])
            _INVESTOR_BRIEF_CACHE.pop(oldest[0], None)


@router.get(
    "/investor/brief/{market}",
    summary="Investor brief — 6-section market intelligence report",
    tags=["Investor"],
)
@limiter.limit("20/minute")
async def investor_brief_json(
    market: str,
    request: Request,
    land_cost_cr: float = Query(default=0.0, ge=0, description="Land cost in Cr (min 0)"),
    area_acres: float = Query(default=0.0, ge=0, description="Land area in acres (min 0)"),
    project_name: str = Query(default="RE_OS Query", description="Project name for the brief"),
):
    canonical = _resolve_market(market)
    if not canonical:
        _investor_brief_requests_total.labels(market=market, status="invalid_market").inc()
        return _err_resp(f"Invalid market: {market}", request, 400, "Investor")

    cache_key = f"{canonical}:{land_cost_cr}:{area_acres}:{project_name}:json"
    cached = _cached_brief(cache_key)
    if cached:
        _investor_brief_cache_hits_total.labels(market=canonical).inc()
        return json.loads(cached)

    _investor_brief_requests_total.labels(market=canonical, status="miss").inc()
    t0 = time.time()
    try:
        from utils.investor_brief_generator import InvestorBriefGenerator

        gen = InvestorBriefGenerator()
        brief = gen.generate(
            market=canonical,
            project_name=project_name,
            land_cost_cr=land_cost_cr,
            area_acres=area_acres,
        )
        data = brief.to_dict()
        data["status"] = "ok"
        _investor_brief_duration_seconds.labels(market=canonical).observe(time.time() - t0)
        _set_cached_brief(cache_key, json.dumps(data))
        logger.debug("[investor_brief] cache miss for %s (%.2fs)", cache_key, time.time() - t0)
        return data
    except Exception as exc:
        _investor_brief_requests_total.labels(market=canonical, status="error").inc()
        logger.error("[investor_brief] %s", exc)
        return _err_resp(str(exc), request, 500, "Investor")


@router.get(
    "/investor/brief/{market}/markdown",
    summary="Investor brief as formatted markdown",
    tags=["Investor"],
)
@limiter.limit("20/minute")
async def investor_brief_markdown(
    market: str,
    request: Request,
    land_cost_cr: float = Query(default=0.0, ge=0),
    area_acres: float = Query(default=0.0, ge=0),
    project_name: str = Query(default="RE_OS Query"),
):
    canonical = _resolve_market(market)
    if not canonical:
        return _err_resp(f"Invalid market: {market}", request, 400, "Investor")

    cache_key = f"{canonical}:{land_cost_cr}:{area_acres}:{project_name}:md"
    cached = _cached_brief(cache_key)
    if cached:
        _investor_brief_cache_hits_total.labels(market=canonical).inc()
        return Response(content=cached, media_type="text/markdown")

    _investor_brief_requests_total.labels(market=canonical, status="miss").inc()
    t0 = time.time()
    try:
        from utils.investor_brief_generator import (
            InvestorBriefGenerator, format_markdown,
        )

        gen = InvestorBriefGenerator()
        brief = gen.generate(
            market=canonical,
            project_name=project_name,
            land_cost_cr=land_cost_cr,
            area_acres=area_acres,
        )
        md = format_markdown(brief)
        _investor_brief_duration_seconds.labels(market=canonical).observe(time.time() - t0)
        _set_cached_brief(cache_key, md)

        from utils.obsidian_sync import write_investor_brief
        obsidian_result = write_investor_brief(canonical, md, project_name, land_cost_cr, area_acres)
        if obsidian_result == "":
            logger.warning("[investor_brief] Obsidian write failed for %s (I/O error)", canonical)
        elif obsidian_result is None:
            logger.debug("[investor_brief] Obsidian vault not mounted — skipped export")

        return Response(content=md, media_type="text/markdown")
    except Exception as exc:
        _investor_brief_requests_total.labels(market=canonical, status="error").inc()
        logger.error("[investor_brief_markdown] %s", exc)
        return _err_resp(str(exc), request, 500, "Investor")
