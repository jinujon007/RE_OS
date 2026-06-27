"""
RE_OS MCP Server — Intelligence Tools as Model Context Protocol (MCP).

Exposes 4 RE_OS intelligence tools over MCP SSE transport on port 8051:
  - rera_search(query, market)      — RERA project search
  - psf_forecast(market, months)    — PSF price forecast (trend-projected)
  - quick_feasibility(...)          — IRR/NPV feasibility via calc_irr engine
  - corridor_score(lat, lon)        — corridor proximity scoring (PostGIS)

Architecture:
  - Starlette ASGI app for SSE + HTTP transport
  - Minimal MCP protocol: /sse (SSE stream) + /message (JSON-RPC POST)
  - DB via utils.db.get_engine() — same pool as main app
  - CORS for web-based MCP inspectors (e.g., mcp.inspect)

GATE-135:
  - Optional auth via MCP_API_KEY env var on /sse and /message (403 if wrong/missing)
  - /health always unauthenticated — includes uptime, cache size, rate limiter state
  - Input bounds validation, 256KB body cap, session TTL cleanup (60s idle)
  - Prometheus metrics: mcp_tool_calls_total, mcp_tool_errors_total (per-tool)

GATE-138 (T-1376–T-1380):
  - Auth: X-API-Key header matching MCP_API_KEY. 403 on mismatch. Empty string = disabled.
  - Cache: 5-min TTL dict cache on psf_forecast and corridor_score (max 500 entries,
    LRU eviction). md5 cache key = tool_name + JSON-sorted args. Thread-safe via Lock.
    In-flight tracking prevents cache stampede on concurrent cache-miss for same key.
  - Rate limiter: 10 req/min per client IP. Token bucket via deque. 429 Retry-After.
    Max 5000 tracked IPs with stale cleanup. Prometheus counter + gauge.
  - Logging: auth failures and rate-limit hits logged at WARNING level with client IP.

Protocol:
  - Implements initialize, notifications/initialized, tools/list, tools/call, ping
  - Proper JSON-RPC error codes per spec (-32602 params, -32601 method, -32000 exec)

Run: python mcp_server/re_os_mcp.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager

from sqlalchemy import text as _sa_text
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from utils.db import get_engine

logger = logging.getLogger("re_os.mcp")

# ── Configuration ───────────────────────────────────────────────────────────

_MCP_API_KEY: str | None = os.environ.get("MCP_API_KEY") or None
_SESSION_TTL_SECONDS: int = 60
_MAX_BODY_BYTES: int = 262144

# ── Cache (T-1377) ───────────────────────────────────────────────────────────

_MCP_CACHE: dict[str, tuple[str, float]] = {}
_MCP_CACHE_LOCK = threading.Lock()
_MCP_CACHE_TTL: float = 300.0
_MCP_CACHE_MAX: int = 500

_CACHED_TOOL_NAMES: frozenset = frozenset({"psf_forecast", "corridor_score", "investor_brief"})


def _cache_key(tool_name: str, arguments: dict) -> str:
    raw = f"{tool_name}:{json.dumps(arguments, sort_keys=True, default=str)}"
    return hashlib.md5(raw.encode()).hexdigest()


def _clear_mcp_cache() -> None:
    with _MCP_CACHE_LOCK:
        _MCP_CACHE.clear()
    with _MCP_CACHE_INFLIGHT_LOCK:
        for event in _MCP_CACHE_INFLIGHT.values():
            event.set()
        _MCP_CACHE_INFLIGHT.clear()


_MCP_CACHE_INFLIGHT: dict[str, threading.Event] = {}
_MCP_CACHE_INFLIGHT_LOCK = threading.Lock()
_MCP_CACHE_INFLIGHT_TIMEOUT: float = 2.0


def _mcp_cache_get(tool: str, args: dict) -> str | None:
    key = _cache_key(tool, args)
    with _MCP_CACHE_LOCK:
        entry = _MCP_CACHE.get(key)
        if entry is not None:
            cached, ts = entry
            if time.monotonic() - ts <= _MCP_CACHE_TTL:
                return cached
            _MCP_CACHE.pop(key, None)

    with _MCP_CACHE_INFLIGHT_LOCK:
        inflight_event = _MCP_CACHE_INFLIGHT.get(key)
        if inflight_event is not None:
            inflight_event.wait(timeout=_MCP_CACHE_INFLIGHT_TIMEOUT)
            with _MCP_CACHE_LOCK:
                entry = _MCP_CACHE.get(key)
                if entry is not None:
                    return entry[0]
            return None
        event = threading.Event()
        _MCP_CACHE_INFLIGHT[key] = event
    return None


def _mcp_cache_set(tool: str, args: dict, result: str) -> None:
    key = _cache_key(tool, args)
    with _MCP_CACHE_LOCK:
        if len(_MCP_CACHE) >= _MCP_CACHE_MAX:
            oldest = min(_MCP_CACHE.items(), key=lambda kv: kv[1][1])
            _MCP_CACHE.pop(oldest[0], None)
        _MCP_CACHE[key] = (result, time.monotonic())
    with _MCP_CACHE_INFLIGHT_LOCK:
        event = _MCP_CACHE_INFLIGHT.pop(key, None)
        if event is not None:
            event.set()


# ── Rate limiter (T-1378) — token bucket, 10 req/min per client IP ─────────

_RATE_LIMITER: dict[str, deque[float]] = {}
_RATE_LIMITER_LOCK = threading.Lock()
_RATE_LIMIT_REQS: int = 10
_RATE_LIMIT_WINDOW: float = 60.0
_RATE_LIMITER_MAX_CLIENTS: int = 5000

_RATE_LIMIT_HITS = 0


def _rate_limiter_cleanup():
    now = time.monotonic()
    with _RATE_LIMITER_LOCK:
        stale_ips = [
            ip for ip, dq in _RATE_LIMITER.items()
            if not dq or now - dq[-1] > _RATE_LIMIT_WINDOW
        ]
        n_clean = 0
        for ip in stale_ips:
            if now - _RATE_LIMITER[ip][-1] > _RATE_LIMIT_WINDOW:
                del _RATE_LIMITER[ip]
                n_clean += 1
        if n_clean:
            logger.debug("[mcp] rate limiter cleaned %d stale IPs (%d remain)", n_clean, len(_RATE_LIMITER))


def _check_rate_limit(client_ip: str) -> str | None:
    now = time.monotonic()
    with _RATE_LIMITER_LOCK:
        if len(_RATE_LIMITER) >= _RATE_LIMITER_MAX_CLIENTS:
            _rate_limiter_cleanup()

        ts_deque = _RATE_LIMITER.get(client_ip)
        if ts_deque is None:
            ts_deque = deque()
            _RATE_LIMITER[client_ip] = ts_deque
        while ts_deque and now - ts_deque[0] > _RATE_LIMIT_WINDOW:
            ts_deque.popleft()
        if len(ts_deque) >= _RATE_LIMIT_REQS:
            oldest = ts_deque[0]
            retry_after = int(_RATE_LIMIT_WINDOW - (now - oldest)) + 1
            global _RATE_LIMIT_HITS
            _RATE_LIMIT_HITS += 1
            logger.warning("[mcp] rate limit exceeded for %s (%d hits total)", client_ip, _RATE_LIMIT_HITS)
            if _rate_limit_hits_total is not None:
                _rate_limit_hits_total.inc()
            return str(retry_after)
        ts_deque.append(now)
    # Update Prometheus gauges periodically (every ~10 calls)
    if _rate_limiter_clients_gauge is not None and (now % 10 < 0.5):
        _rate_limiter_clients_gauge.set(len(_RATE_LIMITER))
    if _mcp_cache_entries_gauge is not None and (now % 10 < 0.5):
        _mcp_cache_entries_gauge.set(len(_MCP_CACHE))
    return None

# ── Optional Prometheus metrics ──────────────────────────────────────────────

try:
    from prometheus_client import Counter as _PCounter, Gauge as _PGauge, REGISTRY as _PRegistry
    _tool_calls_total = _PCounter(
        "mcp_tool_calls_total", "MCP tool calls", ["tool", "status"],
        registry=_PRegistry,
    )
    _tool_errors_total = _PCounter(
        "mcp_tool_errors_total", "MCP tool execution errors", ["tool", "error_code"],
        registry=_PRegistry,
    )
    _rate_limit_hits_total = _PCounter(
        "mcp_rate_limit_hits_total", "MCP rate limit hits by client IP",
        registry=_PRegistry,
    )
    _rate_limiter_clients_gauge = _PGauge(
        "mcp_rate_limiter_clients", "Current MCP rate limiter tracked IPs",
        registry=_PRegistry,
    )
    _mcp_cache_entries_gauge = _PGauge(
        "mcp_cache_entries", "Current MCP cache entries",
        registry=_PRegistry,
    )
except ImportError:
    _tool_calls_total = None
    _tool_errors_total = None
    _rate_limit_hits_total = None
    _rate_limiter_clients_gauge = None
    _mcp_cache_entries_gauge = None


def _inc_tool_call(tool: str, status: str) -> None:
    if _tool_calls_total is not None:
        _tool_calls_total.labels(tool=tool, status=status).inc()


def _inc_tool_error(tool: str, error_code: str) -> None:
    if _tool_errors_total is not None:
        _tool_errors_total.labels(tool=tool, error_code=error_code).inc()

# ── Request tracing ─────────────────────────────────────────────────────────


def _request_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Input validation helpers ────────────────────────────────────────────────


def _validate_bounds(name: str, value: float, lo: float, hi: float) -> str | None:
    if not (lo <= value <= hi):
        return f"{name} must be in [{lo}, {hi}], got {value}"
    return None


# ── DB helpers ──────────────────────────────────────────────────────────────


def _run_query(sql: str, params: dict | None = None, timeout_s: float = 10.0) -> list:
    """Run a read-only SQL query with timeout.

    Returns list of Row objects (empty on error, logged at WARN level).
    Errors are logged at WARN (not ERROR) to prevent log flooding.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(_sa_text(sql), params or {})
            return list(result)
    except Exception as exc:
        logger.warning("[mcp] query failed: %s", exc)
        return []


def _row_to_dict(row) -> dict | None:
    """Convert a SQLAlchemy Row to dict, or None."""
    if row is None:
        return None
    return dict(row._mapping)


# ── Tool implementations ────────────────────────────────────────────────────


def _rera_search(query: str, market: str = "Yelahanka") -> str:
    errors: list[str] = []
    if not query or not query.strip():
        errors.append("query is required")
    valid_markets = {"Yelahanka", "Devanahalli", "Hebbal"}
    if market not in valid_markets:
        errors.append(f"market must be one of {sorted(valid_markets)}, got '{market}'")
    if errors:
        return json.dumps({"status": "validation_error", "errors": errors})

    rows = _run_query(
        """
            SELECT rp.project_name, rp.rera_reg_no, rp.status,
                   rp.address, mm.name as market
            FROM rera_projects rp
            JOIN micro_markets mm ON mm.id = rp.micro_market_id
            WHERE mm.name = :market
              AND (rp.project_name ILIKE :q OR rp.address ILIKE :q)
            LIMIT 20
        """,
        {"market": market, "q": f"%{query.strip()}%"},
    )
    results = [_row_to_dict(r) for r in rows if r]
    return json.dumps({"status": "ok", "count": len(results), "results": results})


def _psf_forecast(market: str = "Yelahanka", months: int = 6) -> str:
    args = {"market": market, "months": months}
    cached = _mcp_cache_get("psf_forecast", args)
    if cached is not None:
        return cached

    valid_markets = {"Yelahanka", "Devanahalli", "Hebbal"}
    if market not in valid_markets:
        return json.dumps({
            "status": "validation_error",
            "errors": [f"market must be one of {sorted(valid_markets)}, got '{market}'"],
        })
    forecast_months = max(1, min(months, 60))

    rows = _run_query(
        """
            SELECT forecast_date, forecast_psf, lower_bound, upper_bound,
                   psf_trend, r_squared, psf_change_pct
            FROM market_forecasts
            WHERE market = :market
            ORDER BY forecast_date DESC
            LIMIT 1
        """,
        {"market": market},
    )
    if not rows:
        return json.dumps({"status": "insufficient_data", "market": market,
                           "note": "No forecast data available for this market"})

    r = _row_to_dict(rows[0])
    base_psf = float(r["forecast_psf"])
    psf_change_pct = r.get("psf_change_pct")
    r_sq = r.get("r_squared")

    projected_psf = base_psf
    if psf_change_pct and float(psf_change_pct) != 0:
        monthly_change = float(psf_change_pct) / 12.0
        projected_psf = base_psf * (1 + monthly_change * forecast_months)

    result = json.dumps({"status": "ok", "result": {
        "market": market,
        "current_forecast_psf": round(base_psf, 2),
        "projected_psf": round(projected_psf, 2),
        "months_forecast": forecast_months,
        "psf_trend": r.get("psf_trend"),
        "r_squared": round(float(r_sq), 4) if r_sq else None,
        "forecast_date": str(r["forecast_date"]),
        "projection_note": "Linear projection from latest trend" if psf_change_pct else "Static — no trend data",
    }})
    _mcp_cache_set("psf_forecast", args, result)
    return result


def _quick_feasibility(land_cost_cr: float, area_acres: float, market: str = "Yelahanka") -> str:
    errors: list[str] = []
    err = _validate_bounds("land_cost_cr", land_cost_cr, 0.01, 1_000_000.0)
    if err:
        errors.append(err)
    err = _validate_bounds("area_acres", area_acres, 0.01, 10_000.0)
    if err:
        errors.append(err)
    valid_markets = {"Yelahanka", "Devanahalli", "Hebbal"}
    if market not in valid_markets:
        errors.append(f"market must be one of {sorted(valid_markets)}, got '{market}'")
    if errors:
        return json.dumps({"status": "validation_error", "errors": errors})

    # Get average PSF from listings
    rows = _run_query(
        """
            SELECT l.price_psf
            FROM listings l
            JOIN micro_markets mm ON mm.id = l.micro_market_id
            WHERE mm.name = :market AND l.price_psf > 0
            ORDER BY l.price_psf
        """,
        {"market": market},
    )
    psf_values = [float(r[0]) for r in rows if r and r[0]]
    if len(psf_values) >= 3:
        # Median to avoid outlier skew
        psf_values.sort()
        avg_psf = psf_values[len(psf_values) // 2]
        n_records = len(psf_values)
    else:
        avg_psf = 8000.0
        n_records = 0

    try:
        from utils.irr_model import calc_irr
        land_cost_abs = land_cost_cr * 1_00_00_000
        sellable_sqft = area_acres * 43560.0 * 0.65  # 65% sellable after FSI + common areas

        irr_result = calc_irr(
            land_cost=land_cost_abs,
            sellable_area_sqft=sellable_sqft,
            sell_psf=avg_psf,
        )
        return json.dumps({"status": "ok", "result": {
            "avg_psf": round(avg_psf, 2),
            "psf_source": "market_listings" if n_records >= 3 else "default_fallback",
            "listings_used": n_records,
            "sellable_sqft": round(sellable_sqft, 2),
            "total_project_cost_cr": round(irr_result.total_project_cost / 1_00_00_000, 2),
            "gross_development_value_cr": round(irr_result.gdv / 1_00_00_000, 2),
            "net_profit_cr": round(irr_result.net_profit / 1_00_00_000, 2),
            "profit_margin_pct": round(irr_result.profit_margin_pct, 1),
            "irr_pct": round(irr_result.simple_irr_pct, 1),
            "verdict": irr_result.verdict,
            "equity_required_cr": round(irr_result.equity_required / 1_00_00_000, 2),
            "payback_months": irr_result.payback_months,
            "inputs": {
                "land_cost_cr": land_cost_cr,
                "area_acres": area_acres,
                "market": market,
            },
        }})
    except ImportError:
        return json.dumps({"status": "error", "error": "IRR model unavailable (numpy-financial not installed)"})
    except Exception as exc:
        logger.warning("[mcp] quick_feasibility calc_irr failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


def _corridor_score(lat: float, lon: float) -> str:
    args = {"lat": lat, "lon": lon}
    cached = _mcp_cache_get("corridor_score", args)
    if cached is not None:
        return cached

    errors: list[str] = []
    err = _validate_bounds("lat", lat, -90.0, 90.0)
    if err:
        errors.append(err)
    err = _validate_bounds("lon", lon, -180.0, 180.0)
    if err:
        errors.append(err)
    if errors:
        return json.dumps({"status": "validation_error", "errors": errors})

    rows = _run_query(
        """
            SELECT cb.name, cb.composite_score, cb.transport_score,
                   cb.commercial_score,
                   ST_Distance(
                       cb.geom::geography,
                       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                   ) as distance_m
            FROM corridor_boundaries cb
            WHERE ST_DWithin(
                cb.geom::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                5000
            )
            ORDER BY distance_m ASC
            LIMIT 1
        """,
        {"lat": lat, "lon": lon},
    )
    if not rows:
        return json.dumps({"status": "ok", "result": {
            "composite_score": 0.0,
            "in_corridor": False,
            "note": "Location not within 5km of any known corridor. Score 0 = no corridor influence.",
        }})

    r = _row_to_dict(rows[0])
    result = json.dumps({"status": "ok", "result": {
        "composite_score": round(float(r["composite_score"]), 4),
        "in_corridor": True,
        "corridor_name": r["name"],
        "transport_score": round(float(r.get("transport_score", 0)), 4),
        "commercial_score": round(float(r.get("commercial_score", 0)), 4),
        "distance_m": round(float(r["distance_m"]), 1),
    }})
    _mcp_cache_set("corridor_score", args, result)
    return result


def _investor_brief(market: str = "Yelahanka", land_cost_cr: float = 0.0,
                    area_acres: float = 0.0, project_name: str = "RE_OS Query") -> str:
    args = {"market": market, "land_cost_cr": land_cost_cr,
            "area_acres": area_acres, "project_name": project_name}
    cached = _mcp_cache_get("investor_brief", args)
    if cached is not None:
        return cached

    errors: list[str] = []
    try:
        from config.settings import TARGET_MARKETS
        valid_markets = set(m.strip() for m in TARGET_MARKETS)
    except Exception:
        valid_markets = {"Yelahanka", "Devanahalli", "Hebbal"}
    if market not in valid_markets:
        errors.append(f"market must be one of {sorted(valid_markets)}, got '{market}'")
    err = _validate_bounds("land_cost_cr", land_cost_cr, 0.0, 1_000_000.0)
    if err:
        errors.append(err)
    err = _validate_bounds("area_acres", area_acres, 0.0, 10_000.0)
    if err:
        errors.append(err)
    if errors:
        return json.dumps({"status": "validation_error", "errors": errors})

    try:
        from utils.investor_brief_generator import InvestorBriefGenerator
        gen = InvestorBriefGenerator()
        brief = gen.generate(market, project_name, land_cost_cr, area_acres)
        data = brief.to_dict()

        # Keep under 2000 chars — strip verbose fields for MCP efficiency
        summary = {
            "status": "ok",
            "market": data["market"],
            "market_overview": {
                "avg_psf": data["market_overview"].get("avg_psf"),
                "psf_range": [data["market_overview"].get("psf_min"),
                              data["market_overview"].get("psf_max")],
                "trend": data["market_overview"].get("psf_trend", {}).get("direction"),
                "rera_projects": data["market_overview"].get("rera_projects"),
            },
            "competitive_landscape": {
                "grade_a_count": data["competitive_landscape"].get("grade_a_count"),
            },
            "financial_summary": {
                "status": data["financial_summary"].get("status"),
                "scenarios": {
                    k: {"irr_pct": v["irr_pct"], "verdict": v["verdict"],
                        "profit_margin_pct": v["profit_margin_pct"]}
                    for k, v in data["financial_summary"].get("scenarios", {}).items()
                } if data["financial_summary"].get("status") == "computed" else {},
            },
            "supply_risk": {
                "pipeline_units": data["supply_risk"].get("pipeline_units"),
                "weeks_of_inventory": data["supply_risk"].get("weeks_of_inventory"),
            },
            "assembly_alerts_count": len(data.get("assembly_alerts", [])),
            "board_verdict": data["board_verdict"].get("decision_flag", "no_verdict"),
        }
        result = json.dumps(summary)
        _mcp_cache_set("investor_brief", args, result)
        return result
    except Exception as exc:
        logger.warning("[mcp] investor_brief failed: %s", exc)
        return json.dumps({"status": "error", "error": str(exc)})


# ── Tool registry ───────────────────────────────────────────────────────────

TOOLS: dict[str, dict] = {
    "rera_search": {
        "name": "rera_search",
        "description": "Search RERA-registered projects by name or location in a specific market. Returns project name, RERA registration number, project status, and address. Limited to 20 results.",
        "handler": _rera_search,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Project name or location search term"},
                "market": {"type": "string", "description": "Market name: Yelahanka, Devanahalli, or Hebbal", "default": "Yelahanka"},
            },
            "required": ["query"],
        },
    },
    "psf_forecast": {
        "name": "psf_forecast",
        "description": "Get PSF (price per square foot) forecast for a market. Returns current forecast PSF, projected PSF for N months out, trend direction, and R-squared confidence. Uses linear projection from the latest weekly forecast model.",
        "handler": _psf_forecast,
        "parameters": {
            "type": "object",
            "properties": {
                "market": {"type": "string", "description": "Market name: Yelahanka, Devanahalli, or Hebbal", "default": "Yelahanka"},
                "months": {"type": "integer", "description": "Number of months to project forward (1-60)", "default": 6},
            },
            "required": [],
        },
    },
    "quick_feasibility": {
        "name": "quick_feasibility",
        "description": "Land deal feasibility assessment using the RE_OS calc_irr engine. Takes land cost, area, and market; returns IRR, profit margin, development cost, GDV, equity required, payback period, and a GO/MARGINAL/NO-GO verdict. Uses median listing PSF from the target market.",
        "handler": _quick_feasibility,
        "parameters": {
            "type": "object",
            "properties": {
                "land_cost_cr": {"type": "number", "description": "Land cost in crores INR (0.01–1,000,000)"},
                "area_acres": {"type": "number", "description": "Land area in acres (0.01–10,000)"},
                "market": {"type": "string", "description": "Market name: Yelahanka, Devanahalli, or Hebbal", "default": "Yelahanka"},
            },
            "required": ["land_cost_cr", "area_acres"],
        },
    },
    "corridor_score": {
        "name": "corridor_score",
        "description": "Score a GPS location based on proximity to known growth corridors. Uses PostGIS ST_DWithin to find the nearest corridor within 5km. Returns composite_score (0-1), corridor name, transport and commercial sub-scores, and distance in metres. Score 0 means no known corridor within range.",
        "handler": _corridor_score,
        "parameters": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude in decimal degrees (-90 to 90)"},
                "lon": {"type": "number", "description": "Longitude in decimal degrees (-180 to 180)"},
            },
            "required": ["lat", "lon"],
        },
    },
    "investor_brief": {
        "name": "investor_brief",
        "description": "Generate a 6-section investor-ready market brief from live RE_OS database. Sections: market_overview (PSF range, trend, absorption), competitive_landscape (Grade A devs), financial_summary (IRR at 3 scenarios), supply_risk, assembly_alerts, board_verdict. No LLM calls — deterministic from DB. Returns JSON under 2000 chars.",
        "handler": _investor_brief,
        "parameters": {
            "type": "object",
            "properties": {
                "market": {"type": "string", "description": "Market name: Yelahanka, Devanahalli, or Hebbal"},
                "land_cost_cr": {"type": "number", "description": "Land cost in crores INR (0.01–1,000,000)"},
                "area_acres": {"type": "number", "description": "Land area in acres (0.01–10,000)"},
                "project_name": {"type": "string", "description": "Optional project name for the brief", "default": "RE_OS Query"},
            },
            "required": ["market", "land_cost_cr", "area_acres"],
        },
    },
}


# ── MCP Protocol — JSON-RPC handler ────────────────────────────────────────

_JSON_RPC_ID: int = 0
_JSON_RPC_ID_LOCK = threading.Lock()


def _next_id() -> int:
    global _JSON_RPC_ID
    with _JSON_RPC_ID_LOCK:
        _JSON_RPC_ID += 1
        return _JSON_RPC_ID


def _make_error(code: int, message: str, data: dict | None = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": None, "error": err}


def _handle_jsonrpc(body: dict, request_id: str = "") -> dict:
    method = body.get("method", "")
    req_id = body.get("id", _next_id())
    params: dict = body.get("params", {})

    # ── ping (liveness) ────────────────────────────────────────────────
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    # ── initialize ─────────────────────────────────────────────────────
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "re_os_mcp", "version": "1.0.2"},
            },
        }

    # ── notifications/initialized (no response) ────────────────────────
    if method == "notifications/initialized":
        logger.debug("[mcp] client initialized (request_id=%s)", request_id)
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    # ── tools/list ─────────────────────────────────────────────────────
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "inputSchema": t["parameters"],
                    }
                    for t in TOOLS.values()
                ]
            },
        }

    # ── tools/call ─────────────────────────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        tool = TOOLS.get(tool_name)
        if not tool:
            _inc_tool_error(tool_name, "not_found")
            return _make_error(-32601, f"Tool not found: {tool_name}",
                               {"available_tools": list(TOOLS.keys())})

        # Parameter validation before dispatch
        param_schema = tool["parameters"]
        required = param_schema.get("required", [])
        missing = [p for p in required if p not in arguments]
        if missing:
            _inc_tool_error(tool_name, "missing_params")
            return _make_error(-32602, f"Missing required parameters: {', '.join(missing)}",
                               {"tool": tool_name, "missing": missing})

        try:
            result_str = tool["handler"](**arguments)
            _inc_tool_call(tool_name, "ok")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": result_str}]},
            }
        except TypeError as exc:
            _inc_tool_error(tool_name, "type_error")
            return _make_error(-32602, f"Parameter type error: {exc}",
                               {"tool": tool_name})
        except Exception as exc:
            _inc_tool_error(tool_name, "execution_error")
            logger.warning("[mcp] tool error (request_id=%s): %s: %s", request_id, tool_name, exc)
            return _make_error(-32000, f"Tool execution error: {exc}")

    # ── Unknown method ─────────────────────────────────────────────────
    return _make_error(-32601, f"Method not found: {method}")


# ── Starlette app ──────────────────────────────────────────────────────────

_SESSIONS: dict[str, asyncio.Queue] = {}
_SESSIONS_LOCK = asyncio.Lock()
_SESSION_TOUCH: dict[str, float] = {}

_MESSAGE_HANDLER_TASKS: set[asyncio.Task] = set()


async def _cleanup_stale_sessions():
    """Background task: evict sessions idle > _SESSION_TTL_SECONDS."""
    while True:
        await asyncio.sleep(15)
        now = time.monotonic()
        stale = [sid for sid, last in _SESSION_TOUCH.items()
                 if now - last > _SESSION_TTL_SECONDS]
        if stale:
            async with _SESSIONS_LOCK:
                for sid in stale:
                    _SESSIONS.pop(sid, None)
                    _SESSION_TOUCH.pop(sid, None)
            if stale:
                logger.debug("[mcp] cleaned %d stale sessions", len(stale))


@asynccontextmanager
async def _lifespan(app_instance):
    cleanup_task = asyncio.create_task(_cleanup_stale_sessions())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    # Close any remaining sessions
    async with _SESSIONS_LOCK:
        remaining = len(_SESSIONS)
        _SESSIONS.clear()
        _SESSION_TOUCH.clear()
    if remaining:
        logger.debug("[mcp] cleaned %d remaining sessions on shutdown", remaining)


_START_TIME: float = time.monotonic()


async def _health(request):
    return JSONResponse({
        "status": "ok",
        "service": "re_os_mcp",
        "version": "1.0.2",
        "auth_required": _MCP_API_KEY is not None,
        "uptime_s": round(time.monotonic() - _START_TIME, 1),
        "tools_count": len(TOOLS),
        "rate_limiter_clients": len(_RATE_LIMITER),
        "rate_limit_hits": _RATE_LIMIT_HITS,
        "cache_entries": len(_MCP_CACHE),
    })


# ── Auth middleware ────────────────────────────────────────────────────────


def _is_authorized(headers: Headers) -> bool:
    if _MCP_API_KEY is None:
        return True  # No auth configured → open
    return headers.get("x-api-key", "") == _MCP_API_KEY


# ── SSE endpoint ───────────────────────────────────────────────────────────


async def _sse(request):
    if not _is_authorized(request.headers):
        logger.warning("[mcp] auth failure on /sse from %s", request.client.host if request.client else "unknown")
        return JSONResponse({"error": "unauthorized — provide X-API-Key header matching MCP_API_KEY env"}, status_code=403)

    client_ip = request.client.host if request.client else "unknown"
    retry_after = _check_rate_limit(client_ip)
    if retry_after is not None:
        return JSONResponse({"error": "rate limit exceeded"}, status_code=429, headers={"Retry-After": retry_after})

    session_id = uuid.uuid4().hex
    queue: asyncio.Queue = asyncio.Queue()
    async with _SESSIONS_LOCK:
        _SESSIONS[session_id] = queue
        _SESSION_TOUCH[session_id] = time.monotonic()

    logger.debug("[mcp] session %s opened", session_id)

    async def event_stream():
        try:
            yield f"event: endpoint\ndata: {json.dumps({'endpoint': f'/message?sessionId={session_id}'})}\n\n"
            while True:
                msg = await queue.get()
                yield f"data: {json.dumps(msg)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            async with _SESSIONS_LOCK:
                _SESSIONS.pop(session_id, None)
                _SESSION_TOUCH.pop(session_id, None)
            logger.debug("[mcp] session %s closed", session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ── Message endpoint ───────────────────────────────────────────────────────


async def _message(request):
    if not _is_authorized(request.headers):
        client_ip = request.client.host if request.client else "unknown"
        logger.warning("[mcp] auth failure on /message from %s", client_ip)
        return JSONResponse(
            _make_error(-32000, "unauthorized — provide X-API-Key header matching MCP_API_KEY env"),
            status_code=403,
        )

    client_ip = request.client.host if request.client else "unknown"
    retry_after = _check_rate_limit(client_ip)
    if retry_after is not None:
        return JSONResponse(
            _make_error(-32000, "rate limit exceeded — try again later"),
            status_code=429,
            headers={"Retry-After": retry_after},
        )

    session_id = request.query_params.get("sessionId", "")
    async with _SESSIONS_LOCK:
        queue = _SESSIONS.get(session_id)

    if not queue:
        return JSONResponse(
            _make_error(-32000, f"Session not found: {session_id}"),
            status_code=404,
        )

    # Update session touch time
    async with _SESSIONS_LOCK:
        _SESSION_TOUCH[session_id] = time.monotonic()

    req_id = _request_id()
    try:
        body_raw = await request.body()
        if len(body_raw) > _MAX_BODY_BYTES:
            return JSONResponse(
                _make_error(-32700, f"Request body exceeds {_MAX_BODY_BYTES} bytes"),
                status_code=413,
            )
        body = json.loads(body_raw)
    except json.JSONDecodeError as exc:
        logger.warning("[mcp] invalid JSON (request_id=%s): %s", req_id, exc)
        return JSONResponse(
            _make_error(-32700, f"Invalid JSON: {exc}"),
            status_code=400,
        )
    except Exception as exc:
        logger.warning("[mcp] body read error (request_id=%s): %s", req_id, exc)
        return JSONResponse(
            _make_error(-32700, str(exc)),
            status_code=400,
        )

    response = _handle_jsonrpc(body, request_id=req_id)
    await queue.put(response)
    return JSONResponse({"ok": True})


# ── App assembly ───────────────────────────────────────────────────────────

app = Starlette(
    debug=False,
    routes=[
        Route("/health", endpoint=_health),
        Route("/sse", endpoint=_sse),
        Route("/message", endpoint=_message, methods=["POST"]),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            allow_credentials=True,
        ),
    ],
    lifespan=_lifespan,
)


def _check_migrations():
    """Run alembic check at startup. Logs warning if migrations are pending."""
    try:
        import subprocess
        result = subprocess.run(
            ["alembic", "check"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("[mcp] alembic check: pending migrations — %s",
                           result.stderr.strip() or result.stdout.strip() or "unknown")
        else:
            logger.info("[mcp] alembic check: schema up to date")
    except FileNotFoundError:
        logger.warning("[mcp] alembic not found — skipping migration check")
    except Exception as exc:
        logger.warning("[mcp] alembic check failed (non-fatal): %s", exc)


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _check_migrations()
    logger.info("Starting RE_OS MCP server on port 8051 (auth=%s)",
                "required" if _MCP_API_KEY else "disabled")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8051, log_level="info",
                access_log=os.environ.get("MCP_ACCESS_LOG", "0") == "1")


if __name__ == "__main__":
    main()
