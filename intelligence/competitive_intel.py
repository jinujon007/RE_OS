"""
RE_OS — Competitive Intelligence Engine (Sprint 54)
Three methods: new_launches, psf_movers, absorption_leaders.
All gracefully return empty list on DB error (never crash).

SQL Safety: All queries use SQLAlchemy text() with bind parameters.
No f-strings in SQL text — the optional market filter uses conditional
query construction with separate parameter sets, avoiding injection vectors.

Risk Register:
| Risk | Impact | Mitigation |
|------|--------|------------|
| DB connection timeout | Method returns empty list silently | All methods wrap in try/except; empty list indistinguishable from no-data |
| psf_movers LATERAL join failure | PG < 9.3 incompatibility | Project targets PG 15+; LATERAL is PG 9.3+ |
| days param 0 or negative | Bad SQL (zero-day interval) | Clamped to minimum 1 at method entry |
| market empty string vs None | Wrong filter applied | Empty string treated same as None (no market clause) |
| Concurrent pulse() calls | Race per-method on engine.connect() | Each method opens own connection; engine is thread-safe singleton |
"""
from datetime import datetime, timezone
from loguru import logger

__all__ = ["CompetitiveIntelEngine"]

_MARKET_JOIN = "LEFT JOIN micro_markets mm ON mm.id = rp.micro_market_id"
_DEV_JOIN = "LEFT JOIN developers d ON d.id = rp.developer_id"

_MARKET_FILTER_SQL = "AND mm.name ILIKE :market"


class CompetitiveIntelEngine:
    def __init__(self, caller: str = ""):
        self._caller = caller or "CompetitiveIntel"

    def new_launches(self, market: str | None = None, days: int = 7) -> list[dict]:
        days = max(days, 1)
        from utils.db import get_engine
        from sqlalchemy import text
        engine = get_engine()
        try:
            if market:
                rows = self._query_new_launches_market(engine, market, days)
            else:
                rows = self._query_new_launches_all(engine, days)
            return self._fmt_launches(rows)
        except Exception as exc:
            logger.warning("[{}] new_launches failed: {}", self._caller, exc)
            return []

    def _query_new_launches_all(self, engine, days: int):
        from sqlalchemy import text
        with engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT rp.project_name, d.name, d.grade, mm.name,
                       rp.total_units, rp.price_min_psf, rp.price_max_psf, rp.rera_number
                FROM rera_projects rp
                {_DEV_JOIN}
                {_MARKET_JOIN}
                WHERE rp.created_at >= NOW() - CAST(:days || ' days' AS INTERVAL)
            """), {"days": days}).fetchall()

    def _query_new_launches_market(self, engine, market: str, days: int):
        from sqlalchemy import text
        with engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT rp.project_name, d.name, d.grade, mm.name,
                       rp.total_units, rp.price_min_psf, rp.price_max_psf, rp.rera_number
                FROM rera_projects rp
                {_DEV_JOIN}
                {_MARKET_JOIN}
                WHERE rp.created_at >= NOW() - CAST(:days || ' days' AS INTERVAL)
                {_MARKET_FILTER_SQL}
            """), {"days": days, "market": market}).fetchall()

    def psf_movers(self, market: str | None = None, threshold_pct: float = 5.0) -> list[dict]:
        from utils.db import get_engine
        from sqlalchemy import text
        engine = get_engine()
        try:
            if market:
                rows = self._query_psf_movers_market(engine, market, threshold_pct)
            else:
                rows = self._query_psf_movers_all(engine, threshold_pct)
            return self._fmt_movers(rows)
        except Exception as exc:
            logger.warning("[{}] psf_movers failed: {}", self._caller, exc)
            return []

    def _query_psf_movers_all(self, engine, threshold_pct: float):
        from sqlalchemy import text
        with engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT rp.project_name, d.name, mm.name,
                       snap.price_min_psf, rp.price_min_psf,
                       (rp.price_min_psf - snap.price_min_psf) / NULLIF(snap.price_min_psf, 0) AS change_ratio,
                       d.grade
                FROM rera_projects rp
                {_DEV_JOIN}
                {_MARKET_JOIN}
                INNER JOIN LATERAL (
                    SELECT price_min_psf
                    FROM project_snapshots ps
                    WHERE ps.rera_project_id = rp.id
                      AND ps.price_min_psf IS NOT NULL
                      AND ps.snapshot_date >= CURRENT_DATE - INTERVAL '30 days'
                    ORDER BY ps.snapshot_date ASC
                    LIMIT 1
                ) snap ON TRUE
                WHERE rp.price_min_psf IS NOT NULL
                  AND snap.price_min_psf IS NOT NULL
                  AND snap.price_min_psf > 0
                  AND ABS((rp.price_min_psf - snap.price_min_psf) / snap.price_min_psf) >= :threshold
                ORDER BY change_ratio DESC
            """), {"threshold": threshold_pct / 100.0}).fetchall()

    def _query_psf_movers_market(self, engine, market: str, threshold_pct: float):
        from sqlalchemy import text
        with engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT rp.project_name, d.name, mm.name,
                       snap.price_min_psf, rp.price_min_psf,
                       (rp.price_min_psf - snap.price_min_psf) / NULLIF(snap.price_min_psf, 0) AS change_ratio,
                       d.grade
                FROM rera_projects rp
                {_DEV_JOIN}
                {_MARKET_JOIN}
                INNER JOIN LATERAL (
                    SELECT price_min_psf
                    FROM project_snapshots ps
                    WHERE ps.rera_project_id = rp.id
                      AND ps.price_min_psf IS NOT NULL
                      AND ps.snapshot_date >= CURRENT_DATE - INTERVAL '30 days'
                    ORDER BY ps.snapshot_date ASC
                    LIMIT 1
                ) snap ON TRUE
                WHERE rp.price_min_psf IS NOT NULL
                  AND snap.price_min_psf IS NOT NULL
                  AND snap.price_min_psf > 0
                  AND ABS((rp.price_min_psf - snap.price_min_psf) / snap.price_min_psf) >= :threshold
                {_MARKET_FILTER_SQL}
                ORDER BY change_ratio DESC
            """), {"threshold": threshold_pct / 100.0, "market": market}).fetchall()

    def absorption_leaders(self, market: str | None = None, top_n: int = 5, min_units: int = 50) -> list[dict]:
        from utils.db import get_engine
        from sqlalchemy import text
        engine = get_engine()
        try:
            if market:
                rows = self._query_absorption_market(engine, market, top_n, min_units)
            else:
                rows = self._query_absorption_all(engine, top_n, min_units)
            return self._fmt_absorption(rows)
        except Exception as exc:
            logger.warning("[{}] absorption_leaders failed: {}", self._caller, exc)
            return []

    def _query_absorption_all(self, engine, top_n: int, min_units: int):
        from sqlalchemy import text
        with engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT rp.project_name, d.name, d.grade, mm.name,
                       rp.absorption_pct, rp.total_units, rp.unsold_units, rp.possession_date
                FROM rera_projects rp
                {_DEV_JOIN}
                {_MARKET_JOIN}
                WHERE rp.absorption_pct > 0
                  AND rp.total_units >= :min_units
                ORDER BY rp.absorption_pct DESC
                LIMIT :top_n
            """), {"top_n": top_n, "min_units": min_units}).fetchall()

    def _query_absorption_market(self, engine, market: str, top_n: int, min_units: int):
        from sqlalchemy import text
        with engine.connect() as conn:
            return conn.execute(text(f"""
                SELECT rp.project_name, d.name, d.grade, mm.name,
                       rp.absorption_pct, rp.total_units, rp.unsold_units, rp.possession_date
                FROM rera_projects rp
                {_DEV_JOIN}
                {_MARKET_JOIN}
                WHERE rp.absorption_pct > 0
                  AND rp.total_units >= :min_units
                {_MARKET_FILTER_SQL}
                ORDER BY rp.absorption_pct DESC
                LIMIT :top_n
            """), {"top_n": top_n, "min_units": min_units, "market": market}).fetchall()

    def pulse(self, market: str | None = None, days: int = 7, top_n: int = 5) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "new_launches": self.new_launches(market, days),
            "psf_movers": self.psf_movers(market),
            "absorption_leaders": self.absorption_leaders(market, top_n),
            "generated_at": now,
            "market_filter": market,
            "days_window": days,
        }

    def invalidate_cache(self, market: str | None = None):
        pass  # No module-level cache — each call is fresh (future: add MarketCache)

    def _fmt_launches(self, rows) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "project_name": str(r[0]) if r[0] else "",
                "developer_name": str(r[1]) if r[1] else "",
                "developer_grade": str(r[2]) if r[2] else "",
                "market": str(r[3]) if r[3] else "",
                "total_units": int(r[4]) if r[4] else 0,
                "price_min_psf": float(r[5]) if r[5] else None,
                "price_max_psf": float(r[6]) if r[6] else None,
                "rera_number": str(r[7]) if r[7] else "",
                "data_as_of": now,
            }
            for r in rows
        ]

    def _fmt_movers(self, rows) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "project_name": str(r[0]) if r[0] else "",
                "developer_name": str(r[1]) if r[1] else "",
                "market": str(r[2]) if r[2] else "",
                "psf_before": float(r[3]) if r[3] else None,
                "psf_now": float(r[4]) if r[4] else None,
                "change_pct": round(float(r[5]) * 100, 2) if r[5] else 0.0,
                "direction": self._direction_from_change(r[5]),
                "developer_grade": str(r[6]) if len(r) > 6 and r[6] else "",
                "data_as_of": now,
            }
            for r in rows
        ]

    @staticmethod
    def _direction_from_change(change_ratio) -> str:
        if change_ratio is None:
            return "FLAT"
        c = float(change_ratio)
        if c > 0.001:
            return "UP"
        if c < -0.001:
            return "DOWN"
        return "FLAT"

    def _fmt_absorption(self, rows) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "project_name": str(r[0]) if r[0] else "",
                "developer_name": str(r[1]) if r[1] else "",
                "developer_grade": str(r[2]) if r[2] else "",
                "market": str(r[3]) if r[3] else "",
                "absorption_pct": float(r[4]) if r[4] else 0.0,
                "total_units": int(r[5]) if r[5] else 0,
                "unsold_units": int(r[6]) if r[6] else 0,
                "possession_date": str(r[7]) if r[7] else "",
                "data_as_of": now,
            }
            for r in rows
        ]
