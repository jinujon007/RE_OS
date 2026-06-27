"""
RE_OS Dashboard — Health routes
"""

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text as _sa_text

from dashboard.state import limiter, _get_sa_engine, templates
from utils.discord_notifier import _CHANNEL_ENV_MAP

logger = logging.getLogger("re_os.dashboard")

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    summary="Full health check",
)
@limiter.limit("60/minute")
async def health(request: Request):
    services = {"agents": "ok"}
    try:
        with _get_sa_engine().connect() as conn:
            conn.execute(_sa_text("SELECT 1"))
        services["postgres"] = "ok"
    except Exception:
        services["postgres"] = "error"
    try:
        import redis as redis_lib
        r = redis_lib.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
        r.ping()
        r.close()
        services["redis"] = "ok"
    except Exception:
        services["redis"] = "error"
    try:
        import httpx
        resp = httpx.get("http://ollama:11434/api/tags", timeout=3.0)
        services["ollama"] = "ok" if resp.status_code == 200 else "warn"
    except Exception:
        services["ollama"] = "warn"
    try:
        from chromadb import PersistentClient
        _chroma_path = os.environ.get("CHROMA_DB_PATH", "/app/data/chroma")
        _test_client = PersistentClient(path=_chroma_path)
        _test_client.heartbeat()
        services["chroma"] = "ok"
    except Exception:
        services["chroma"] = "error"
    try:
        with _get_sa_engine().connect() as conn:
            row = conn.execute(
                _sa_text("""
                SELECT micro_market, status, started_at, duration_seconds
                FROM agent_runs ORDER BY started_at DESC LIMIT 1
            """)
            ).fetchone()
        if row:
            services["last_run"] = {
                "market": row[0],
                "status": row[1],
                "started_at": row[2].isoformat() if row[2] else None,
                "duration_seconds": row[3],
            }
        else:
            services["last_run"] = None
    except Exception:
        services["last_run"] = None
    discord_status = {}
    for channel, env_key in _CHANNEL_ENV_MAP.items():
        discord_status[channel] = bool(os.environ.get(env_key, "").strip())
    general_webhook = bool(os.environ.get("DISCORD_WEBHOOK_URL", "").strip())
    channels_missing = [
        ch for ch, configured in discord_status.items()
        if not configured and not general_webhook
    ]
    services["discord"] = {
        "configured": general_webhook or any(discord_status.values()),
        "general_webhook": general_webhook,
        "channels_missing": channels_missing,
    }
    try:
        from utils.data_quality import DataQualityMonitor
        from config.slos import all_slo_status
        freshness = DataQualityMonitor.freshness_score()
        slo_result = all_slo_status(freshness)
        seed_stale = DataQualityMonitor.check_seed_staleness()
        locality_scores = {}
        try:
            from config.locality_aliases import KNOWN_ALIEN_LOCALITIES
            from config.settings import TARGET_MARKETS
            for m in TARGET_MARKETS:
                locality_scores[m] = DataQualityMonitor.locality_validation_score(m.strip())
        except Exception as exc:
            logger.warning("[health] locality_score check failed: %s", exc)
        try:
            with _get_sa_engine().connect() as conn:
                null_rate = conn.execute(
                    _sa_text("""
                        SELECT ROUND(
                            COUNT(CASE WHEN sentiment_score IS NULL THEN 1 END)::numeric
                            / NULLIF(COUNT(*), 0), 3
                        )
                        FROM news_articles
                        WHERE created_at >= NOW() - INTERVAL '7 days'
                    """)
                ).scalar()
            sentiment_null_rate = float(null_rate) if null_rate is not None else None
        except Exception:
            sentiment_null_rate = None
        services["data_quality"] = {
            "slo_pass": slo_result["slo_pass"],
            "slo_fail": slo_result["slo_fail"],
            "freshness": freshness if freshness else None,
            "seed_stale_warnings": seed_stale[:5],
            "locality_scores": locality_scores,
            "sentiment_null_rate": sentiment_null_rate,
        }
    except Exception as exc:
        logger.warning("[health] data_quality check failed: %s", exc)
        services["data_quality"] = {
            "slo_pass": 0, "slo_fail": 0, "freshness": None,
            "seed_stale_warnings": [], "locality_scores": {},
            "sentiment_null_rate": None,
        }
    try:
        with _get_sa_engine().connect() as conn:
            scraper_health = {}
            for mkt in ["Yelahanka", "Hebbal", "Devanahalli"]:
                row = conn.execute(
                    _sa_text("""
                        SELECT metadata, completed_at FROM agent_runs
                        WHERE agent_name = 'rera_scraper'
                          AND micro_market = :market
                          AND task_type = 'scrape_complete'
                        ORDER BY completed_at DESC LIMIT 1
                    """),
                    {"market": mkt},
                ).fetchone()
                if row:
                    md = row[0]
                    scraper_health[mkt] = {
                        "record_count": md.get("record_count") if isinstance(md, dict) else None,
                        "fallback_triggered": md.get("fallback_triggered") if isinstance(md, dict) else None,
                        "path_used": md.get("path_used") if isinstance(md, dict) else None,
                        "run_at": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]) if row[1] else None,
                    }
                else:
                    scraper_health[mkt] = None
            services["scraper_health"] = scraper_health
    except Exception as exc:
        logger.warning("[health] scraper_health check failed: %s", exc)
        services["scraper_health"] = {"error": str(exc)}
    try:
        from utils.backup import check_backup_staleness, get_backup_dir
        stale_info = check_backup_staleness()
        backup_status = {
            "stale": stale_info["stale"],
            "latest_backup_age_hours": stale_info["age_hours"],
            "latest_backup_file": stale_info["latest_file"],
            "backup_dir": get_backup_dir(),
        }
        try:
            with _get_sa_engine().connect() as conn:
                ts_row = conn.execute(
                    _sa_text("""
                        SELECT created_at FROM agent_runs
                        WHERE agent_name = 'backup' AND event_type = 'db_backup' AND status = 'success'
                        ORDER BY created_at DESC LIMIT 1
                    """)
                ).fetchone()
                backup_status["latest_backup_timestamp"] = ts_row[0].isoformat() if ts_row else None
        except Exception:
            backup_status["latest_backup_timestamp"] = None
        backup_status["backup_ok"] = (
            not backup_status["stale"] and backup_status["latest_backup_timestamp"] is not None
        )
        services["backup_status"] = backup_status
    except Exception as exc:
        logger.warning("[health] backup_status check failed: %s", exc)
        services["backup_status"] = {
            "backup_ok": False, "stale": True,
            "latest_backup_age_hours": None, "latest_backup_timestamp": None,
        }
    try:
        from config.llm_router import get_router_status, get_circuit_states
        router_status = get_router_status()
        circuit_states = get_circuit_states()
        services["llm"] = {
            "configured": any(router_status.get("providers", {}).values()),
            "heavy_providers": sum(
                1 for p in ["groq", "gemini", "nvidia", "sambanova", "openrouter", "cloudflare"]
                if router_status.get("providers", {}).get(p)
            ),
            "circuit_states": circuit_states,
        }
    except Exception as exc:
        logger.warning("[health] llm check failed: %s", exc)
        services["llm"] = {
            "configured": False, "heavy_providers": 0, "circuit_states": {},
        }
    try:
        engine = _get_sa_engine()
        pool = engine.pool
        services["db_pool"] = {
            "size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }
    except Exception:
        services["db_pool"] = {"size": 0, "checked_out": 0, "overflow": 0}
    return services


@router.get(
    "/health/live",
    summary="Lightweight liveness probe (no deps)",
)
def health_liveness():
    return {"agents": "ok", "postgres": "ok", "redis": "ok", "ollama": "warn", "chroma": "error"}


@router.get("/alert/test", summary="Send test alert")
@limiter.limit("5/hour")
async def test_alert(request: Request):
    from utils.notifier import send_alert
    sent = send_alert("Test from RE_OS", "INFO")
    return {"sent": sent}


@router.get(
    "/mcp/health",
    summary="MCP server health passthrough — checks re_os_mcp:8051/health",
)
@limiter.limit("30/minute")
async def mcp_health(request: Request):
    import httpx
    mcp_url = os.environ.get("MCP_HEALTH_URL", "http://re_os_mcp:8051/health")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(mcp_url)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "mcp_status": "ok",
                    "mcp_tools": data.get("tools_count", data.get("mcp_tools", 4)),
                    "mcp_auth_required": data.get("auth_required", False),
                    "mcp_version": data.get("version", "unknown"),
                }
            return JSONResponse(
                {"mcp_status": "error", "detail": f"MCP returned {resp.status_code}"},
                status_code=503,
            )
    except httpx.ConnectError:
        return JSONResponse(
            {"mcp_status": "down", "detail": "Cannot connect to re_os_mcp:8051"},
            status_code=503,
        )
    except Exception as exc:
        logger.warning("[mcp_health] %s", exc)
        return JSONResponse(
            {"mcp_status": "error", "detail": str(exc)},
            status_code=503,
        )
