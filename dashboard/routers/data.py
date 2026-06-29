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


class VillagePriorityItem(BaseModel):
    village: str
    market: str
    assembly_signal_count: int = 0
    max_confidence: float = 0.0
    last_deed_ingested: str | None = None
    priority_score: float = 0.0
    priority_rank: int | None = None
    kaveri_url_hint: str


class DownloadGuideResponse(BaseModel):
    villages: list[VillagePriorityItem]
    generated_at: str
    guide_message: str


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
    if not name:
        return ""
    normalized = name.strip().lower()
    normalized = re.sub(r"\s*\([^)]*\)", "", normalized)
    normalized = re.sub(r"\s+(pvt|ltd|private\s+limited|llp)$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _names_match(a: str | None, b: str | None) -> bool:
    na = _normalize_name(a)
    nb = _normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
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
                "confidence": round(float(r[3]), 3) if r[3] is not None else 0.0,
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


# ── Decision Journal Panel (T-1406) ──────────────────────────────────────


@router.get("/decision-journal", tags=["Decision Journal"], summary="Decision Journal dashboard panel")
def decision_journal_panel(request: Request):
    return templates.TemplateResponse(request, "decision_journal.html")


# ── Deed Throughput Panel (T-1407) ───────────────────────────────────────


@router.get("/deed-throughput", tags=["Deeds"], summary="Deed Throughput Kill Criteria dashboard panel")
def deed_throughput_panel(request: Request):
    return templates.TemplateResponse(request, "deed_throughput.html")


# ── Assembly Signals Panel (T-1408) ──────────────────────────────────────


@router.get("/assembly-signals", tags=["Assembly"], summary="Assembly Signals dashboard panel")
def assembly_signals_panel(request: Request):
    return templates.TemplateResponse(request, "assembly_signals.html")


# ── Assembly Timeline Time-Series (T-1443) ──────────────────────────────


class AssemblyTimelineItem(BaseModel):
    week_start: str
    cluster_count: int
    avg_confidence: float
    high_confidence_count: int


class AssemblyTimelineResponse(BaseModel):
    market: str
    timeline: list[AssemblyTimelineItem]
    total_weeks: int
    generated_at: str
    source: str = "view"


_assembly_timeline_requests_total = _counter(
    "assembly_timeline_requests_total", "Assembly timeline requests", ["source", "status"],
)
_assembly_timeline_duration_seconds = _histogram(
    "assembly_timeline_duration_seconds", "Assembly timeline query duration",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


@router.get(
    "/intel/assembly-timeline",
    response_model=AssemblyTimelineResponse,
    summary="Assembly cluster count time-series by market (weekly windows, 1 year)",
    tags=["Assembly"],
)
@limiter.limit("60/minute")
async def assembly_timeline(
    request: Request,
    market: str = Query(..., min_length=2, description="Market name (Yelahanka/Devanahalli/Hebbal)"),
):
    t0 = time.time()
    try:
        from utils.assembly_detector import AssemblyDetector
        from sqlalchemy import text as sa_text

        canonical = _resolve_market(market)
        if not canonical:
            _assembly_timeline_requests_total.labels(source="request", status="invalid_market").inc()
            return _err_resp(f"unknown market: {market}", request, 400, "Assembly")

        engine = _get_sa_engine()
        timeline: list[dict] = []
        source = "view"

        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    sa_text("""
                        SELECT week_start, cluster_count, avg_confidence, high_confidence_count
                        FROM v_assembly_weekly_trend
                        WHERE market ILIKE :mkt
                        ORDER BY week_start ASC
                        LIMIT 52
                    """),
                    {"mkt": canonical},
                ).fetchall()
                for r in rows:
                    timeline.append({
                        "week_start": str(r.week_start),
                        "cluster_count": int(r.cluster_count),
                        "avg_confidence": float(r.avg_confidence) if r.avg_confidence is not None else 0.0,
                        "high_confidence_count": int(r.high_confidence_count),
                    })
        except Exception:
            logger.debug("[assembly_timeline] view query failed, falling back to detect_time_series")
            timeline = []

        if not timeline:
            source = "detector"
            detector = AssemblyDetector()
            ts = detector.detect_time_series(canonical)
            timeline = [{
                "week_start": t["week_start"],
                "cluster_count": t["cluster_count"],
                "avg_confidence": t["avg_confidence"],
                "high_confidence_count": t["high_confidence_count"],
            } for t in ts]

        elapsed = time.time() - t0
        _assembly_timeline_duration_seconds.observe(elapsed)
        _assembly_timeline_requests_total.labels(source=source, status="ok").inc()

        return JSONResponse(
            content=AssemblyTimelineResponse(
                market=canonical,
                timeline=[AssemblyTimelineItem(**t) for t in timeline],
                total_weeks=len(timeline),
                generated_at=datetime.now(timezone.utc).isoformat(),
                source=source,
            ).model_dump(),
            headers={
                "Cache-Control": "private, max-age=60, must-revalidate",
                "X-Source": source,
            },
        )
    except Exception as exc:
        elapsed = time.time() - t0
        _assembly_timeline_requests_total.labels(source="error", status="internal_error").inc()
        logger.error("[assembly_timeline] %s (elapsed=%.2fs)", exc, elapsed)
        return _err_resp(str(exc), request, 500, "Assembly")


# ── Dashboard Badges (T-1409) ────────────────────────────────────────────


_deed_throughput_badge_hits_total = _counter(
    "deed_throughput_badge_hits_total", "Badge endpoint queries", ["status"],
)


class DashboardBadgesResponse(BaseModel):
    decision_journal_today: int = 0
    assembly_high_confidence: int = 0
    deed_status: str = "unknown"
    as_of: str = ""


@router.get(
    "/dashboard/badges",
    summary="Real-time nav badge counts (decision journal today, assembly high confidence, deed status)",
    tags=["Dashboard"],
)
@limiter.limit("60/minute")
async def dashboard_badges(request: Request):
    try:
        t0 = time.time()
        with _get_sa_engine().connect() as conn:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            dj_today = conn.execute(
                _sa_text(
                    "SELECT COUNT(*) FROM decision_journal WHERE entry_date = :d"
                ), {"d": today_str},
            ).scalar() or 0
            assembly_high = conn.execute(
                _sa_text(
                    "SELECT COUNT(*) FROM assembly_signals WHERE "
                    "(confidence_score > 0.75 OR confidence > 0.75) "
                    "AND (resolved_at IS NULL OR status = 'open')"
                ),
            ).scalar() or 0
            deed_row = conn.execute(
                _sa_text(
                    "SELECT current_week_count FROM v_deed_throughput_weekly "
                    "ORDER BY week_start DESC LIMIT 1"
                ),
            ).fetchone()
            current = int(deed_row[0]) if deed_row else 0
        elapsed = time.time() - t0
        if current == 0:
            deed_status = "critical"
        elif current < 50:
            deed_status = "at_risk"
        else:
            deed_status = "on_track"
        _deed_throughput_badge_hits_total.labels(status=deed_status).inc()
        db_query_duration_seconds.labels(query_name="dashboard_badges").observe(elapsed)
        return DashboardBadgesResponse(
            decision_journal_today=dj_today,
            assembly_high_confidence=assembly_high,
            deed_status=deed_status,
            as_of=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        logger.warning("[dashboard_badges] %s", exc)
        return DashboardBadgesResponse(as_of=datetime.now(timezone.utc).isoformat())


# ── Market Forecaster / Spread / Supply ─────────────────────────────────


@router.get(
    "/market/forecast/{market}",
    summary="PSF forecast for a market (3/6/12-month horizons)",
)
@limiter.limit("30/hour")
async def market_forecast(market: str, request: Request = None):
    try:
        from utils.psf_forecaster import PSFForecaster
        f = PSFForecaster()
        forecast = f.forecast(market)
        return {
            "market": market,
            "trend_direction": forecast.trend_direction,
            "current_psf": forecast.current_psf,
            "forecast_3m": forecast.forecast_3m,
            "forecast_6m": forecast.forecast_6m,
            "forecast_12m": forecast.forecast_12m,
            "data_points": forecast.data_points,
            "mae_pct": forecast.mae_pct,
            "status": forecast.status,
        }
    except Exception as exc:
        logger.warning("[market_forecast] %s", exc)
        return _err_resp(str(exc), None, 500, "Data")


@router.get(
    "/market/spread",
    summary="PSF spread distribution across listings for a market (Chart.js histogram)",
)
async def market_spread(
    market: str = Query(default="Yelahanka", description="Market name"),
    bins: int = Query(default=20, ge=5, le=50, description="Number of histogram bins"),
):
    try:
        from utils.db import get_engine
        from sqlalchemy import text as sa_text
        canonical = _normalize_market(market)
        if not canonical:
            return _err_resp("invalid market", None, 400, "Data")
        with get_engine().connect() as conn:
            prices = conn.execute(
                sa_text("""
                    SELECT l.price_psf
                    FROM listings l
                    JOIN micro_markets m ON m.id = l.micro_market_id
                    WHERE m.name = :market
                      AND l.price_psf > 1000 AND l.price_psf < 50000
                    ORDER BY l.price_psf
                """),
                {"market": canonical},
            ).fetchall()
        psf_values = sorted([float(r[0]) for r in prices if r[0] is not None])
        if not psf_values:
            return {"market": canonical, "bins": [], "spread": [], "min": None, "max": None, "count": 0}
        min_psf = psf_values[0]
        max_psf = psf_values[-1]
        total = len(psf_values)
        bin_edges = [min_psf + (max_psf - min_psf) * i / bins for i in range(bins + 1)]
        counts = [0] * bins
        idx = 0
        for i in range(bins):
            lo = bin_edges[i]
            hi = bin_edges[i + 1] if i < bins - 1 else bin_edges[-1]
            while idx < total and psf_values[idx] <= hi:
                counts[i] += 1
                idx += 1
            if i == bins - 1:
                while idx < total and psf_values[idx] <= hi:
                    counts[i] += 1
                    idx += 1
        spread_data = [
            {
                "bin_start": round(bin_edges[i], 0),
                "bin_end": round(bin_edges[i + 1], 0),
                "count": counts[i],
            }
            for i in range(bins)
        ]
        return {
            "market": canonical,
            "bins": bins,
            "spread": spread_data,
            "min": round(min_psf, 0),
            "max": round(max_psf, 0),
            "count": total,
        }
    except Exception as exc:
        logger.warning("[market_spread] %s", exc)
        return _err_resp(str(exc), None, 500, "Data")


@router.get(
    "/market/supply-pipeline/{market}",
    summary="Supply pipeline (upcoming RERA) for a market",
)
async def market_supply_pipeline(market: str):
    try:
        from utils.db import get_engine
        from sqlalchemy import text as sa_text
        canonical = _normalize_market(market)
        if not canonical:
            return _err_resp("invalid market", None, 400, "Data")
        with get_engine().connect() as conn:
            rows = conn.execute(
                sa_text("""
                    SELECT sp.project_name, sp.developer, sp.estimated_units,
                           sp.launch_quarter, sp.status, sp.rera_id
                    FROM supply_pipeline sp
                    WHERE sp.market = :m
                      AND sp.status IN ('registered', 'pre_launch', 'upcoming')
                    ORDER BY sp.launch_quarter NULLS LAST
                    LIMIT 100
                """),
                {"m": canonical},
            ).fetchall()
        pipeline = [
            {
                "project_name": r[0], "developer": r[1],
                "estimated_units": int(r[2]) if r[2] else None,
                "launch_quarter": r[3], "status": r[4], "rera_id": r[5],
            }
            for r in rows
        ]
        return {"market": canonical, "pipeline": pipeline, "count": len(pipeline)}
    except Exception as exc:
        logger.warning("[market_supply_pipeline] %s", exc)
        return _err_resp(str(exc), None, 500, "Data")


# ── Forecast Accuracy (GATE-139) ────────────────────────────────────────


@router.get(
    "/forecast/accuracy/{market}",
    summary="PSF forecast accuracy — comparing past forecasts to actuals",
)
@limiter.limit("20/hour")
async def forecast_accuracy(market: str, request: Request = None):
    try:
        from utils.forecast_accuracy import get_forecast_accuracy
        canonical = _normalize_market(market)
        if not canonical:
            return _err_resp("invalid market", None, 400, "Data")
        result = get_forecast_accuracy(canonical)
        return {"market": canonical, "accuracy": result}
    except Exception as exc:
        logger.warning("[forecast_accuracy] %s", exc)
        return _err_resp(str(exc), None, 500, "Data")


# ── Forecast Accuracy Panel ─────────────────────────────────────────────


@router.get("/forecast-accuracy", tags=["Forecast"], summary="Forecast Accuracy dashboard panel")
def forecast_accuracy_panel(request: Request):
    return templates.TemplateResponse(request, "forecast_accuracy.html")


# ── Government Policy Panel ─────────────────────────────────────────────


@router.get("/govt-policy", tags=["Policy"], summary="Government Policy dashboard panel")
def govt_policy_panel(request: Request):
    return templates.TemplateResponse(request, "govt_policy.html")


# ── Content Studio Panel ────────────────────────────────────────────────


@router.get("/content-studio", tags=["Content"], summary="Content Studio dashboard panel")
def content_studio_panel(request: Request):
    return templates.TemplateResponse(request, "content_studio.html")


# ── Parcel Explorer Panel ───────────────────────────────────────────────


@router.get("/parcel", tags=["Parcel"], summary="Parcel Explorer dashboard panel")
def parcel_panel(request: Request):
    return templates.TemplateResponse(request, "parcel.html")


# ── Optimizer Panel ─────────────────────────────────────────────────────


@router.get("/optimizer", tags=["Optimizer"], summary="Portfolio Optimizer dashboard panel")
def optimizer_panel(request: Request):
    return templates.TemplateResponse(request, "optimizer.html")


# ── Shareholders Panel ──────────────────────────────────────────────────


@router.get("/shareholders", tags=["Shareholders"], summary="Shareholders dashboard panel")
def shareholders_panel(request: Request):
    return templates.TemplateResponse(request, "shareholders.html")


# ── Process Audit Panel ─────────────────────────────────────────────────


@router.get("/process-audit", tags=["Audit"], summary="Process Audit dashboard panel")
def process_audit_panel(request: Request):
    return templates.TemplateResponse(request, "process_audit.html")


# ── PR Studio Panel ─────────────────────────────────────────────────────


@router.get("/pr-studio", tags=["PR"], summary="PR Studio dashboard panel")
def pr_studio_panel(request: Request):
    return templates.TemplateResponse(request, "pr_studio.html")


# ── Digest Panel ────────────────────────────────────────────────────────


@router.get("/digest", tags=["Digest"], summary="Weekly Digest dashboard panel")
def digest_panel(request: Request):
    return templates.TemplateResponse(request, "digest.html")


# ── Projects Panel ──────────────────────────────────────────────────────


@router.get("/projects", tags=["Projects"], summary="Projects dashboard panel")
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


# ── Multi-market Compare (T-1426) ─────────────────────────────────────


_COMPARE_CACHE: dict[str, tuple[str, float]] = {}
_COMPARE_CACHE_TTL = 120.0
_COMPARE_CACHE_LOCK = threading.Lock()


def _cached_compare(key: str) -> str | None:
    with _COMPARE_CACHE_LOCK:
        entry = _COMPARE_CACHE.get(key)
        if entry and time.time() - entry[1] < _COMPARE_CACHE_TTL:
            return entry[0]
    return None


def _set_cached_compare(key: str, value: str) -> None:
    with _COMPARE_CACHE_LOCK:
        _COMPARE_CACHE[key] = (value, time.time())
        if len(_COMPARE_CACHE) > 50:
            oldest = min(_COMPARE_CACHE.items(), key=lambda kv: kv[1][1])
            _COMPARE_CACHE.pop(oldest[0], None)


_DEFAULT_MARKETS = ("Yelahanka", "Devanahalli", "Hebbal")


@router.get(
    "/intel/investor/compare",
    summary="Compare up to 3 markets side-by-side on key investor metrics",
    tags=["Investor"],
)
@limiter.limit("20/minute")
async def investor_compare(
    request: Request,
    markets: str = Query(
        default="Yelahanka,Devanahalli,Hebbal",
        description="Comma-separated market names (max 3)",
    ),
):
    raw_list = [m.strip() for m in markets.split(",") if m.strip()]
    if not raw_list:
        return _err_resp("at least one market required", request, 400, "Investor")
    if len(raw_list) > 3:
        return _err_resp(
            f"max 3 markets supported, got {len(raw_list)}",
            request, 400, "Investor",
        )

    canonical_list = []
    for name in raw_list:
        c = _normalize_market(name)
        if not c:
            return _err_resp(f"invalid market: {name}", request, 400, "Investor")
        canonical_list.append(c)

    cache_key = ",".join(canonical_list)
    cached = _cached_compare(cache_key)
    if cached:
        return json.loads(cached)

    from utils.investor_brief_generator import InvestorBriefGenerator

    results = []
    for name in canonical_list:
        try:
            gen = InvestorBriefGenerator()
            brief = gen.generate(market=name)
            mo = brief.market_overview or {}
            bv = brief.board_verdict or {}
            results.append({
                "market": name,
                "avg_psf": mo.get("avg_psf", 0),
                "board_verdict": bv.get("decision_flag", bv.get("verdict", "NEUTRAL")),
                "assembly_alert_count": len(brief.assembly_alerts or []),
                "psf_range": [mo.get("psf_min"), mo.get("psf_max")],
            })
        except Exception as exc:
            logger.warning("[investor_compare] failed for %s: %s", name, exc)
            results.append({"market": name, "error": str(exc)})

    response = {
        "markets": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(results),
    }
    _set_cached_compare(cache_key, json.dumps(response))
    return response


_VEL_FALLBACK_YEARS = 3


def _resolve_market_psf_values(engine, sa_text) -> list[float]:
    """Get avg PSF for all 3 tracked markets. Tries mat view first, falls back to listings."""
    queries = [
        sa_text("""
            SELECT micro_market, avg_listing_psf
            FROM v_market_brief_mat
            WHERE micro_market ILIKE ANY (ARRAY['%Yelahanka%', '%Devanahalli%', '%Hebbal%'])
        """),
        sa_text("""
            SELECT mm.name, ROUND(AVG(l.price_psf)::numeric, 0) AS avg_psf
            FROM listings l
            JOIN micro_markets mm ON mm.id = l.micro_market_id
            WHERE mm.name IN ('Yelahanka', 'Devanahalli', 'Hebbal')
              AND l.price_psf > 1000 AND l.price_psf < 50000
            GROUP BY mm.name
        """),
    ]
    for q in queries:
        try:
            with engine.connect() as conn:
                rows = conn.execute(q).fetchall()
            values = [float(r[1]) for r in rows if r[1] is not None]
            if values:
                return values
        except Exception:
            continue
    return []


# ── VEL Target PSF Analysis (T-1429) ──────────────────────────────────


@router.get(
    "/intel/investor/vel-analysis",
    summary="VEL target PSF analysis — IRR, competitor gap, recommendation",
    tags=["Investor"],
)
@limiter.limit("20/minute")
async def vel_analysis(
    request: Request,
    land_cost_cr: float = Query(..., gt=0, description="Land cost in crores"),
    area_acres: float = Query(..., gt=0, description="Land area in acres"),
    target_psf: float = Query(..., gt=0, description="Target selling PSF"),
):
    try:
        from utils.db import get_engine
        from sqlalchemy import text as sa_text

        engine = get_engine()
        psf_values = _resolve_market_psf_values(engine, sa_text)
        if not psf_values:
            return _err_resp(
                "could not determine market avg PSF — no data available",
                request, 500, "Investor",
            )

        avg_market_psf = sum(psf_values) / len(psf_values)
        competitor_gap_pct = round(
            (target_psf - avg_market_psf) / avg_market_psf * 100, 1
        )
        sellable_sqft = area_acres * 43560 * 0.65 * 2.5
        gross_revenue = sellable_sqft * target_psf
        land_cost_inr = land_cost_cr * 1_00_00_000

        try:
            from utils.irr_model import calc_irr
            irr_result = calc_irr(land_cost_inr, sellable_sqft, target_psf)
            irr_at_target_psf = irr_result.simple_irr_pct
        except Exception:
            irr_at_target_psf = round(
                (gross_revenue / land_cost_inr - 1) / _VEL_FALLBACK_YEARS * 100, 1
            )

        if irr_at_target_psf > 25 and competitor_gap_pct < 10:
            entry_recommendation = "STRONG_BUY"
        elif irr_at_target_psf > 18:
            entry_recommendation = "BUY"
        elif irr_at_target_psf > 12:
            entry_recommendation = "HOLD"
        else:
            entry_recommendation = "PASS"

        return {
            "competitor_gap_pct": competitor_gap_pct,
            "irr_at_target_psf": irr_at_target_psf,
            "entry_recommendation": entry_recommendation,
            "avg_market_psf": round(avg_market_psf, 0),
            "sellable_sqft": round(sellable_sqft, 0),
            "gross_revenue_cr": round(gross_revenue / 1_00_00_000, 2),
            "land_cost_cr": land_cost_cr,
        }
    except Exception as exc:
        logger.error("[vel_analysis] %s", exc)
        return _err_resp(str(exc), request, 500, "Investor")


# ── VEL Competitive Report (T-1456) ──────────────────────────────────


_vel_competitive_report_requests_total = _counter(
    "vel_competitive_report_requests_total",
    "VEL competitive report requests by market and status",
    ["market", "status"],
)
_vel_competitive_report_duration_seconds = _histogram(
    "vel_competitive_report_duration_seconds",
    "VEL competitive report query duration in seconds",
    ["market"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
_vel_competitive_report_cache_hits_total = _counter(
    "vel_competitive_report_cache_hits_total",
    "VEL competitive report cache hits by market",
    ["market"],
)

_VEL_COMPETITIVE_REPORT_CACHE: dict[str, tuple[str, float]] = {}
_VEL_COMPETITIVE_REPORT_CACHE_TTL = 120.0
_VEL_COMPETITIVE_REPORT_CACHE_LOCK = threading.Lock()


def _cached_vel_comp(key: str) -> str | None:
    with _VEL_COMPETITIVE_REPORT_CACHE_LOCK:
        entry = _VEL_COMPETITIVE_REPORT_CACHE.get(key)
        if entry and time.time() - entry[1] < _VEL_COMPETITIVE_REPORT_CACHE_TTL:
            return entry[0]
    return None


def _set_cached_vel_comp(key: str, value: str) -> None:
    with _VEL_COMPETITIVE_REPORT_CACHE_LOCK:
        _VEL_COMPETITIVE_REPORT_CACHE[key] = (value, time.time())
        if len(_VEL_COMPETITIVE_REPORT_CACHE) > 50:
            oldest = min(_VEL_COMPETITIVE_REPORT_CACHE.items(), key=lambda kv: kv[1][1])
            _VEL_COMPETITIVE_REPORT_CACHE.pop(oldest[0], None)


@router.get(
    "/intel/vel/competitive-report",
    summary="VEL competitive report — Grade A devs, PSF trend, absorption, pipeline",
    tags=["VEL"],
)
@limiter.limit("20/minute")
async def vel_competitive_report(
    request: Request,
    target_market: str = Query(default="Yelahanka", min_length=2, description="Target market name"),
):
    t0 = time.time()
    try:
        canonical = _resolve_market(target_market)
        if not canonical:
            _vel_competitive_report_requests_total.labels(market=target_market, status="invalid_market").inc()
            return _err_resp(f"unknown market: {target_market}", request, 400, "VEL")

        cache_key = f"vel_comp:{canonical}"
        cached = _cached_vel_comp(cache_key)
        if cached:
            _vel_competitive_report_cache_hits_total.labels(market=canonical).inc()
            _vel_competitive_report_requests_total.labels(market=canonical, status="hit").inc()
            return JSONResponse(
                content=json.loads(cached),
                headers={"Cache-Control": "private, max-age=120, stale-while-revalidate=60"},
            )

        engine = _get_sa_engine()
        grade_a_competitors: list[dict] = []
        psf_trend_3m: dict = {"current": None, "prior": None, "change_pct": None}
        absorption_rate: float | None = None
        launch_pipeline_units: int = 0

        # (1) Grade A devs with active RERA projects
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    _sa_text("""
                        SELECT d.name, COUNT(*) AS project_count
                        FROM rera_projects rp
                        JOIN micro_markets mm ON mm.id = rp.micro_market_id
                        JOIN developers d ON d.id = rp.developer_id
                        WHERE mm.name = :mkt
                          AND rp.project_status = 'ongoing'
                          AND d.grade = 'A'
                        GROUP BY d.name
                        ORDER BY project_count DESC
                    """),
                    {"mkt": canonical},
                ).fetchall()
            grade_a_competitors = [
                {"developer": str(r[0]), "project_count": int(r[1])}
                for r in rows
            ]
        except Exception as exc:
            logger.debug("[vel_competitive_report] grade A query: %s", exc)

        # (2) PSF trend 3mo from project_snapshots
        try:
            with engine.connect() as conn:
                this_month = conn.execute(
                    _sa_text("""
                        SELECT AVG(avg_psf)
                        FROM project_snapshots ps
                        JOIN micro_markets mm ON mm.id = ps.micro_market_id
                        WHERE mm.name = :mkt
                          AND ps.snapshot_date >= DATE_TRUNC('month', NOW()) - INTERVAL '1 month'
                          AND ps.avg_psf IS NOT NULL
                    """),
                    {"mkt": canonical},
                ).scalar()
                prior_month = conn.execute(
                    _sa_text("""
                        SELECT AVG(avg_psf)
                        FROM project_snapshots ps
                        JOIN micro_markets mm ON mm.id = ps.micro_market_id
                        WHERE mm.name = :mkt
                          AND ps.snapshot_date >= DATE_TRUNC('month', NOW()) - INTERVAL '4 months'
                          AND ps.snapshot_date < DATE_TRUNC('month', NOW()) - INTERVAL '2 months'
                          AND ps.avg_psf IS NOT NULL
                    """),
                    {"mkt": canonical},
                ).scalar()
            if this_month is not None:
                psf_trend_3m["current"] = round(float(this_month), 0)
            if prior_month is not None:
                psf_trend_3m["prior"] = round(float(prior_month), 0)
            if this_month is not None and prior_month is not None and float(prior_month) > 0:
                psf_trend_3m["change_pct"] = round(
                    (float(this_month) - float(prior_month)) / float(prior_month) * 100, 1
                )
        except Exception as exc:
            logger.debug("[vel_competitive_report] PSF trend query: %s", exc)

        # (3) Launch pipeline: upcoming projects sum units
        try:
            with engine.connect() as conn:
                pipeline_row = conn.execute(
                    _sa_text("""
                        SELECT COALESCE(SUM(sp.estimated_units), 0)
                        FROM supply_pipeline sp
                        WHERE sp.market ILIKE :mkt
                          AND sp.status IN ('registered', 'pre_launch', 'upcoming')
                    """),
                    {"mkt": canonical},
                ).scalar()
            launch_pipeline_units = int(pipeline_row or 0)
        except Exception as exc:
            logger.debug("[vel_competitive_report] pipeline query: %s", exc)

        # (4) Absorption rate from v_market_brief
        try:
            with engine.connect() as conn:
                abs_row = conn.execute(
                    _sa_text("""
                        SELECT absorption_rate FROM v_market_brief
                        WHERE micro_market ILIKE :mkt
                        LIMIT 1
                    """),
                    {"mkt": canonical},
                ).scalar()
            if abs_row is not None:
                absorption_rate = round(float(abs_row), 2)
        except Exception as exc:
            logger.debug("[vel_competitive_report] absorption query: %s", exc)

        change_pct = psf_trend_3m.get("change_pct")
        if change_pct is not None and change_pct > 5:
            recommendation = "PREMIUM_WINDOW"
        elif change_pct is not None and change_pct > 0:
            recommendation = "STEADY"
        else:
            recommendation = "PRICE_PRESSURE"

        _vel_competitive_report_duration_seconds.labels(market=canonical).observe(time.time() - t0)
        _vel_competitive_report_requests_total.labels(market=canonical, status="ok").inc()

        body = {
            "grade_a_competitors": grade_a_competitors,
            "psf_trend_3m": psf_trend_3m,
            "absorption_rate": absorption_rate,
            "launch_pipeline_units": launch_pipeline_units,
            "recommendation": recommendation,
            "market": canonical,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        _set_cached_vel_comp(cache_key, json.dumps(body))
        return JSONResponse(
            content=body,
            headers={"Cache-Control": "private, max-age=120, stale-while-revalidate=60"},
        )
    except Exception as exc:
        _vel_competitive_report_requests_total.labels(market=target_market, status="error").inc()
        logger.error("[vel_competitive_report] %s", exc)
        return _err_resp(str(exc), request, 500, "VEL")


# ── VEL Pricing Sensitivity (T-1457) ─────────────────────────────────


_vel_pricing_sensitivity_requests_total = _counter(
    "vel_pricing_sensitivity_requests_total",
    "VEL pricing sensitivity requests by market and status",
    ["market", "status"],
)


@router.get(
    "/intel/vel/pricing-sensitivity",
    summary="VEL pricing sensitivity — PSF distribution, absorption shift, risk band",
    tags=["VEL"],
)
@limiter.limit("20/minute")
async def vel_pricing_sensitivity(
    request: Request,
    market: str = Query(..., min_length=2, description="Market name"),
    target_psf: float = Query(..., gt=0, description="Target selling PSF"),
):
    try:
        canonical = _resolve_market(market)
        if not canonical:
            _vel_pricing_sensitivity_requests_total.labels(market=market, status="invalid_market").inc()
            return _err_resp(f"unknown market: {market}", request, 400, "VEL")

        engine = _get_sa_engine()
        psf_values: list[float] = []

        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    _sa_text("""
                        SELECT ps.avg_psf
                        FROM project_snapshots ps
                        JOIN micro_markets mm ON mm.id = ps.micro_market_id
                        WHERE mm.name = :mkt
                          AND ps.snapshot_date >= NOW() - INTERVAL '90 days'
                          AND ps.avg_psf IS NOT NULL
                          AND ps.avg_psf > 1000
                          AND ps.avg_psf < 50000
                        ORDER BY ps.avg_psf
                    """),
                    {"mkt": canonical},
                ).fetchall()
            psf_values = sorted([float(r[0]) for r in rows if r[0] is not None])
        except Exception as exc:
            logger.debug("[vel_pricing_sensitivity] PSF query: %s", exc)

        _PSF_FALLBACK_P25 = 4500.0
        _PSF_FALLBACK_P50 = 5500.0
        _PSF_FALLBACK_P75 = 7000.0

        note = ""
        if len(psf_values) < 3:
            note = "Insufficient PSF data — using market-wide fallback estimates"
            p25 = _PSF_FALLBACK_P25
            p50 = _PSF_FALLBACK_P50
            p75 = _PSF_FALLBACK_P75
        else:
            def _linear_percentile(sorted_vals: list[float], p: float) -> float:
                n = len(sorted_vals)
                k = (n - 1) * p
                f = int(k)
                c = f + 1 if f + 1 < n else f
                return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])
            n = len(psf_values)
            p25 = _linear_percentile(psf_values, 0.25)
            p50 = _linear_percentile(psf_values, 0.50)
            p75 = _linear_percentile(psf_values, 0.75)

        absorption_shift_psf = round(p75 * 1.1, 0)

        if target_psf <= p50:
            risk_band = "LOW"
        elif target_psf <= p75:
            risk_band = "MODERATE"
        else:
            risk_band = "HIGH"

        premium_over_median_pct = round((target_psf - p50) / p50 * 100, 1) if p50 > 0 else 0.0

        _vel_pricing_sensitivity_requests_total.labels(market=canonical, status="ok").inc()

        return {
            "target_psf": target_psf,
            "p25": round(p25, 0),
            "p50": round(p50, 0),
            "p75": round(p75, 0),
            "absorption_shift_psf": absorption_shift_psf,
            "risk_band": risk_band,
            "premium_over_median_pct": premium_over_median_pct,
            "note": note,
            "market": canonical,
            "data_points": len(psf_values),
        }
    except Exception as exc:
        _vel_pricing_sensitivity_requests_total.labels(market=market, status="error").inc()
        logger.error("[vel_pricing_sensitivity] %s", exc)
        return _err_resp(str(exc), request, 500, "VEL")


# ── VEL Obsidian Pack Export (T-1458) ─────────────────────────────────


class VELExportObsidianRequest(BaseModel):
    target_market: str
    land_cost_cr: float | None = None
    area_acres: float | None = None
    target_psf: float | None = None


@router.post(
    "/intel/vel/export-obsidian",
    summary="Export VEL competitive + pricing + brief as Obsidian markdown pack",
    tags=["VEL"],
)
@limiter.limit("10/minute")
async def vel_export_obsidian(
    request: Request,
    body: VELExportObsidianRequest,
):
    try:
        market = body.target_market.strip()
        if not market:
            return _err_resp("target_market required", request, 400, "VEL")

        canonical = _resolve_market(market)
        if not canonical:
            return _err_resp(f"unknown market: {market}", request, 400, "VEL")

        from utils.investor_brief_generator import InvestorBriefGenerator
        from utils.obsidian_sync import write_vel_pack

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        # Build competitive report + pricing sensitivity (single connection)
        engine = _get_sa_engine()
        grade_a_rows: list[dict] = []
        p50_val = 5500.0
        risk_val = "MODERATE"

        try:
            with engine.connect() as conn:
                grade_rows = conn.execute(
                    _sa_text("""
                        SELECT d.name, COUNT(*) AS project_count
                        FROM rera_projects rp
                        JOIN micro_markets mm ON mm.id = rp.micro_market_id
                        JOIN developers d ON d.id = rp.developer_id
                        WHERE mm.name = :mkt
                          AND rp.project_status = 'ongoing'
                          AND d.grade = 'A'
                        GROUP BY d.name
                        ORDER BY project_count DESC
                    """),
                    {"mkt": canonical},
                ).fetchall()
                grade_a_rows = [{"developer": str(r[0]), "project_count": int(r[1])} for r in grade_rows]

                psf_rows = conn.execute(
                    _sa_text("""
                        SELECT avg_psf FROM project_snapshots ps
                        JOIN micro_markets mm ON mm.id = ps.micro_market_id
                        WHERE mm.name = :mkt
                          AND ps.snapshot_date >= NOW() - INTERVAL '90 days'
                          AND ps.avg_psf IS NOT NULL
                          AND ps.avg_psf > 1000 AND ps.avg_psf < 50000
                        ORDER BY ps.avg_psf
                    """),
                    {"mkt": canonical},
                ).fetchall()
                p_vals = sorted([float(r[0]) for r in psf_rows if r[0] is not None])
                if len(p_vals) >= 3:
                    n = len(p_vals)
                    p50_val = p_vals[int(n * 0.50)]
                    p75_val = p_vals[int(n * 0.75)]
                    tp = body.target_psf or p50_val * 1.2
                    risk_val = "LOW" if tp <= p50_val else "MODERATE" if tp <= p75_val else "HIGH"
        except Exception:
            pass

        # Investor brief
        brief_md = ""
        try:
            gen = InvestorBriefGenerator()
            brief = gen.generate(market=canonical)
            from utils.investor_brief_generator import format_markdown
            brief_md = format_markdown(brief)
        except Exception:
            brief_md = "*Investor brief data unavailable.*"

        ga_lines = "\n".join(
            f"- **{g['developer']}** — {g['project_count']} projects"
            for g in grade_a_rows[:10]
        ) if grade_a_rows else "*No Grade A developer data.*"

        isoTs = now.isoformat(timespec="seconds")
        sections = [
            f"# VEL Intel Pack — {canonical}",
            "",
            f"**Generated:** {isoTs}",
            "",
            "## 1. Competitive Report",
            "",
            "### Grade A Developers",
            ga_lines,
            "",
            "## 2. Pricing Sensitivity",
            "",
            f"- **Market Median PSF:** ₹{p50_val:,.0f}",
            f"- **Risk Band:** {risk_val}",
            "",
            "## 3. Investor Brief",
            "",
            brief_md,
            "",
        ]
        md_content = "\n".join(sections)

        result = write_vel_pack(canonical, md_content)
        if result:
            return {
                "obsidian_path": result,
                "generated_at": now.isoformat(timespec="seconds"),
            }

        placeholder = (
            f"03 LLS/02 Projects/VEL/(AI) VEL Intel Pack {canonical} {date_str}.md"
        )
        return {
            "obsidian_path": placeholder,
            "generated_at": now.isoformat(timespec="seconds"),
            "note": "OBSIDIAN_VAULT_PATH not set — placeholder path returned",
        }
    except Exception as exc:
        logger.error("[vel_export_obsidian] %s", exc)
        return _err_resp(str(exc), request, 500, "VEL")


# ── Corridor Backtest Accuracy (T-1448) ──────────────────────────────


_backtest_accuracy_requests_total = _counter(
    "backtest_accuracy_requests_total",
    "Corridor backtest accuracy requests by market and status",
    ["market", "status"],
)
_backtest_accuracy_duration_seconds = _histogram(
    "backtest_accuracy_duration_seconds",
    "Corridor backtest accuracy query duration in seconds",
    ["market"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


class CorridorBacktestItem(BaseModel):
    corridor: str
    corridor_id: str
    psf_t24: float | None = None
    psf_t12: float | None = None
    psf_now: float | None = None
    actual_change_pct: float | None = None


class CorridorBacktestResponse(BaseModel):
    market: str
    corridors: list[CorridorBacktestItem]
    overall_mape: float | None = None
    best_corridor: str | None = None
    worst_corridor: str | None = None
    data_points: int = 0
    lookback_months: int = 24
    generated_at: str = ""


@router.get(
    "/intel/corridors/backtest-accuracy",
    response_model=CorridorBacktestResponse,
    summary="Corridor backtest accuracy — historical PSF change per corridor vs actual",
    tags=["Corridors"],
)
@limiter.limit("20/minute")
async def corridor_backtest_accuracy(
    request: Request,
    market: str = Query(..., min_length=2, description="Market name (Yelahanka/Devanahalli/Hebbal)"),
    lookback_months: int = Query(default=24, ge=6, le=60, description="Backtest window in months (6-60)"),
):
    t0 = time.time()
    generated_at = datetime.now(timezone.utc).isoformat()
    try:
        canonical = _resolve_market(market)
        if not canonical:
            _backtest_accuracy_requests_total.labels(market=market, status="invalid_market").inc()
            return _err_resp(f"unknown market: {market}", request, 400, "Corridors")

        from utils.corridor_scorer import CorridorScorer

        scorer = CorridorScorer()
        results = scorer.backtest_psf_history(canonical, lookback_months=lookback_months)

        valid_changes = [
            r for r in results if r["actual_change_pct"] is not None
        ]
        overall_mape = (
            round(sum(abs(r["actual_change_pct"]) for r in valid_changes) / len(valid_changes), 1)
            if len(valid_changes) >= 1
            else None
        )

        best_corr_str = worst_corr_str = None
        if valid_changes:
            best = max(valid_changes, key=lambda r: r["actual_change_pct"])
            worst = min(valid_changes, key=lambda r: r["actual_change_pct"])
            best_corr_str = f"{best['corridor']} ({best['actual_change_pct']:+.1f}%)"
            worst_corr_str = f"{worst['corridor']} ({worst['actual_change_pct']:+.1f}%)"

        corridors_model = [
            CorridorBacktestItem(
                corridor=r["corridor"],
                corridor_id=r["corridor_id"],
                psf_t24=r["psf_t24"],
                psf_t12=r["psf_t12"],
                psf_now=r["psf_now"],
                actual_change_pct=r["actual_change_pct"],
            )
            for r in results
        ]

        response = CorridorBacktestResponse(
            market=canonical,
            corridors=corridors_model,
            overall_mape=overall_mape,
            best_corridor=best_corr_str,
            worst_corridor=worst_corr_str,
            data_points=len(valid_changes),
            lookback_months=lookback_months,
            generated_at=generated_at,
        )

        _backtest_accuracy_duration_seconds.labels(market=canonical).observe(time.time() - t0)
        _backtest_accuracy_requests_total.labels(market=canonical, status="ok").inc()

        json_body = response.model_dump_json()
        etag = compute_etag(json_body)
        etag_resp = check_etag(request, etag)
        if etag_resp:
            return etag_resp

        return JSONResponse(
            content=json.loads(json_body),
            headers={"ETag": f'"{etag}"', "Cache-Control": "private, max-age=30"},
        )
    except Exception as exc:
        _backtest_accuracy_requests_total.labels(market=market, status="error").inc()
        logger.error("[corridor_backtest_accuracy] %s", exc)
        return _err_resp(str(exc), request, 500, "Corridors")


# ── Export to Obsidian (T-1428) ───────────────────────────────────────


class ExportObsidianRequest(BaseModel):
    market: str
    project_name: str = "RE_OS Query"
    land_cost_cr: float = 0.0
    area_acres: float = 0.0


@router.post(
    "/intel/investor/export-obsidian",
    summary="Export investor brief to Obsidian vault",
    tags=["Investor"],
)
@limiter.limit("10/minute")
async def export_obsidian(
    request: Request,
    body: ExportObsidianRequest,
):
    market = body.market.strip()
    if not market:
        return _err_resp("market required", request, 400, "Investor")

    canonical = _resolve_market(market)
    if not canonical:
        return _err_resp(f"invalid market: {market}", request, 400, "Investor")

    from utils.investor_brief_generator import InvestorBriefGenerator

    try:
        gen = InvestorBriefGenerator()
        brief = gen.generate(
            market=canonical,
            project_name=body.project_name,
            land_cost_cr=body.land_cost_cr,
            area_acres=body.area_acres,
        )
        brief_dict = brief.to_dict()

        from utils.obsidian_sync import write_investor_brief
        result = write_investor_brief(canonical, brief_dict)
        if result:
            return {
                "obsidian_path": result,
                "generated_at": brief_dict["generated_at"],
            }

        return {
            "obsidian_path": (
                f"03 LLS/01 Wiki/markets/{canonical.lower()}/"
                f"(AI) Investor Brief {canonical} {brief_dict['generated_at'][:10]}.md"
            ),
            "generated_at": brief_dict["generated_at"],
            "note": "OBSIDIAN_VAULT_PATH not set — placeholder path returned",
        }
    except Exception as exc:
        logger.error("[export_obsidian] %s", exc)
        return _err_resp(str(exc), request, 500, "Investor")


# ── Investor Brief Dashboard Panel (T-1427) ──────────────────────────


@router.get("/investor-brief", tags=["Investor"], summary="Investor Brief dashboard panel")
async def investor_brief_panel(request: Request):
    return templates.TemplateResponse(request, "investor_brief.html")


# ── Deed Download Guide (T-1453) ──────────────────────────────────────

_download_guide_requests_total = _counter(
    "download_guide_requests_total",
    "Download guide requests by market and status",
    ["market", "status"],
)


@router.get(
    "/deeds/download-guide",
    response_model=DownloadGuideResponse,
    summary="Priority villages for Form 17 deed downloads this week — ranked by assembly signal density",
    tags=["Deeds"],
    responses={
        200: {"description": "List of priority villages sorted by intelligence value"},
        401: {"description": "Missing or invalid API key"},
        500: {"description": "Internal error"},
    },
)
@limiter.limit("20/minute")
async def download_guide(
    request: Request,
    market: str | None = Query(default=None, min_length=2, description="Market filter (optional) — case-insensitive substring match"),
    top_n: int = Query(default=5, ge=1, le=10, description="Max villages to return (1-10)"),
):
    try:
        from utils.deed_progress import get_priority_villages

        villages = get_priority_villages(market=market, top_n=top_n)
        for i, v in enumerate(villages, 1):
            v["priority_rank"] = i

        _download_guide_requests_total.labels(market=market or "all", status="success").inc()
        return DownloadGuideResponse(
            villages=villages,
            generated_at=datetime.now(timezone.utc).isoformat(),
            guide_message=(
                "This week: download Form 17 Index II for these villages "
                "in Kaveri Online Services. Highest assembly signal density "
                "→ highest deed intelligence value."
            ),
        )
    except Exception as exc:
        _download_guide_requests_total.labels(market=market or "all", status="error").inc()
        logger.error("[download_guide] %s", exc)
        return _err_resp(str(exc), request, 500, "Deeds")
