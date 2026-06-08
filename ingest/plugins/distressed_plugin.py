"""
RE_OS — Distressed Plugin

Five-phase distressed/JD-JV signal collector:

1. **RERA distress scan** — existing delay/incompletion ranking.
2. **BDA e-auction scraping** — best-effort auction feed.
3. **SARFAESI notice search** — placeholder feed.
4. **RERA stall detection** — overdue non-completed projects by developer.
5. **NCLT news detection** — insolvency-related developer mentions.

Then: persist raw signals + compute/persist `signal_type='computed'` blended
developer distress scores for downstream OpportunityEngine and BD context use.

RISK REGISTER:
- Indiankanoon litigation search is NOT implemented because the API
  requires an authentication token that is not part of the RE_OS
  security model. See TASK_QUEUE.md risk register for status.
- BDA e-auction endpoint is reverse-engineered and may break without
  notice. Monitor logs for "[DistressedPlugin]" WARNING messages.
- SARFAESI data quality depends on bank publication frequency.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import text

from ingest.base import DataPlugin, ParsedRecord
from utils.db import get_engine

__all__ = ["DistressedPlugin"]

_BDA_AUCTION_URL = "https://bdaeauction.karnataka.gov.in/api/auctions/active"
_SCRAPING_HEADERS = {
    "User-Agent": "RE_OS/1.0 (market-intel-system)",
    "Accept": "application/json",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_bda_auctions(market_hint: str, max_items: int = 10) -> list[dict]:
    """Fetch active BDA e-auction properties.

    Returns an empty list on any failure (portal unreachable, parse error, …)
    so the plugin never blocks on a third-party API being down.
    """
    try:
        req = urllib.request.Request(
            _BDA_AUCTION_URL,
            headers=_SCRAPING_HEADERS,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read())
        results = []
        items = raw if isinstance(raw, list) else raw.get("data", raw.get("auctions", []))
        for item in (items or [])[:max_items]:
            results.append({
                "property_id": str(item.get("id", "")),
                "location": str(item.get("location", "")),
                "area_sqft": float(item.get("areaSqft", 0) or 0),
                "reserve_price_lakh": float(item.get("reservePrice", 0) or 0) / 100000,
                "auction_date": str(item.get("auctionDate", "")),
                "property_type": str(item.get("propertyType", "land")),
                "source": "bda_eauction",
            })
        if results:
            logger.info("[DistressedPlugin] {} BDA auctions fetched", len(results))
        return results
    except Exception as exc:
        logger.debug("[DistressedPlugin] BDA auction fetch failed (non-fatal): {}", exc)
    return []


def _search_sarfaesi_auctions(market_hint: str) -> list[dict]:
    """Search SARFAESI bank-auctioned properties.

    NOT YET IMPLEMENTED — banks publish SARFAESI notices on individual
    portals (PSB Auctions, Indian Bank e-auction, SBI e-auction, etc.)
    with no unified API. Implementation requires:
    - Per-bank portal scraping or
    - A third-party aggregator feed.

    Returns empty list as a no-op placeholder.
    """
    # TODO: Implement SARFAESI aggregation when a reliable source is identified.
    # Candidate sources:
    #   - https://www.psbauctions.in (PSB consortium portal)
    #   - https://bankeauctions.com (private aggregator)
    logger.debug("[DistressedPlugin] SARFAESI search not implemented — returning empty set")
    return []


class DistressedPlugin(DataPlugin):
    plugin_id = "distressed_scan"
    source_id = "rera_distressed_scan"

    @staticmethod
    def _normalize_market(market: str | None) -> str:
        return (market or "").strip()

    @staticmethod
    def _normalize_developer_name(name: str | None) -> str:
        return " ".join((name or "Unknown").split()) or "Unknown"

    def _get_rera_schema_columns(self) -> set[str]:
        try:
            with get_engine().connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'rera_projects'
                        """
                    )
                ).fetchall()
            return {str(row.column_name) for row in rows}
        except Exception as exc:
            logger.debug("[DistressedPlugin] rera schema introspection failed: {}", exc)
            return set()

    def _detect_rera_stalls(self, market: str) -> list[dict]:
        """Detect developers with overdue non-completed RERA projects."""
        market = self._normalize_market(market)
        columns = self._get_rera_schema_columns()
        completion_expr = (
            "rp.expected_completion_date"
            if "expected_completion_date" in columns
            else "rp.possession_date"
        )
        status_expr = (
            "rp.status"
            if "status" in columns
            else "rp.project_status"
        )
        try:
            with get_engine().connect() as conn:
                rows = conn.execute(
                    text(
                        f"""
                        WITH stalled AS (
                            SELECT
                                COALESCE(d.name, rp.developer_name, 'Unknown') AS developer_name,
                                COALESCE(mm.name, :market) AS market,
                                COUNT(*) AS stall_count
                            FROM rera_projects rp
                            LEFT JOIN developers d ON d.id = rp.developer_id
                            LEFT JOIN micro_markets mm ON mm.id = rp.micro_market_id
                            WHERE (:market IS NULL OR mm.name ILIKE :market_like)
                              AND {completion_expr} IS NOT NULL
                              AND {completion_expr} < NOW() - INTERVAL '12 months'
                              AND LOWER(COALESCE({status_expr}, '')) NOT IN (
                                  'completed', 'oc_received', 'possession_offered'
                              )
                            GROUP BY COALESCE(d.name, rp.developer_name, 'Unknown'), COALESCE(mm.name, :market)
                        ),
                        totals AS (
                            SELECT
                                COALESCE(d.name, rp.developer_name, 'Unknown') AS developer_name,
                                COUNT(*) AS total_projects
                            FROM rera_projects rp
                            LEFT JOIN developers d ON d.id = rp.developer_id
                            LEFT JOIN micro_markets mm ON mm.id = rp.micro_market_id
                            WHERE (:market IS NULL OR mm.name ILIKE :market_like)
                            GROUP BY COALESCE(d.name, rp.developer_name, 'Unknown')
                        )
                        SELECT
                            s.developer_name,
                            s.market,
                            s.stall_count,
                            LEAST(
                                ROUND(s.stall_count::numeric / GREATEST(COALESCE(t.total_projects, 1), 1), 4),
                                1.0
                            ) AS stall_ratio
                        FROM stalled s
                        LEFT JOIN totals t ON t.developer_name = s.developer_name
                        ORDER BY stall_ratio DESC, stall_count DESC, developer_name ASC
                        """
                    ),
                    {"market": market, "market_like": f"%{market}%" if market else None},
                ).fetchall()
        except Exception as exc:
            logger.warning("[DistressedPlugin] RERA stall detection failed for {}: {}", market, exc)
            return []

        return [
            {
                "developer_name": self._normalize_developer_name(row.developer_name),
                "market": str(row.market),
                "stall_count": int(row.stall_count or 0),
                "stall_ratio": max(0.0, min(float(row.stall_ratio or 0.0), 1.0)),
                "signal_type": "rera_stall",
            }
            for row in rows
        ]

    def _detect_nclt_from_news(self, market: str) -> list[dict]:
        """Group insolvency-related news mentions by known developer."""
        market = self._normalize_market(market)
        try:
            with get_engine().connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        WITH matched AS (
                            SELECT
                                CASE
                                    WHEN LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%brigade%' THEN 'Brigade'
                                    WHEN LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%prestige%' THEN 'Prestige'
                                    WHEN LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%sobha%' THEN 'Sobha'
                                    WHEN LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%godrej%' THEN 'Godrej'
                                    WHEN LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%puravankara%' THEN 'Puravankara'
                                    WHEN LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%mantri%' THEN 'Mantri'
                                    WHEN LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%total environment%' THEN 'Total Environment'
                                    ELSE NULL
                                END AS developer_name
                            FROM news_articles
                            WHERE created_at >= NOW() - INTERVAL '180 days'
                              AND (:market IS NULL OR COALESCE(title, '') ILIKE :market_like OR COALESCE(content, '') ILIKE :market_like)
                              AND (
                                  LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%nclt%'
                                  OR LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%insolvency%'
                                  OR LOWER(COALESCE(title, '') || ' ' || COALESCE(content, '')) LIKE '%bankruptcy%'
                              )
                        )
                        SELECT developer_name, COUNT(*) AS mention_count
                        FROM matched
                        WHERE developer_name IS NOT NULL
                        GROUP BY developer_name
                        ORDER BY mention_count DESC, developer_name ASC
                        """
                    ),
                    {"market": market, "market_like": f"%{market}%" if market else None},
                ).fetchall()
        except Exception as exc:
            logger.warning("[DistressedPlugin] NCLT news detection failed for {}: {}", market, exc)
            return []

        return [
            {
                "developer_name": self._normalize_developer_name(row.developer_name),
                "mention_count": int(row.mention_count or 0),
                "signal_type": "nclt_news",
                "market": market,
            }
            for row in rows
        ]

    def _compute_and_persist_scores(self, market: str, signals: list[dict]) -> list[dict]:
        from utils.distressed_developer import compute_developer_distress_score

        developers = sorted({
            self._normalize_developer_name(signal.get("developer_name"))
            for signal in signals
            if signal.get("developer_name") and signal.get("signal_type") in {"rera_stall", "nclt_news"}
        })
        computed: list[dict] = []
        for developer_name in developers:
            score = compute_developer_distress_score(developer_name, market)
            computed.append({
                "developer_name": developer_name,
                "market": market,
                "signal_type": "computed",
                "distress_score": max(0.0, min(float(score or 0.0), 1.0)),
            })
        return computed

    def _persist_distress_signals(self, market: str, signals: list[dict], ingest_log_id: str | None = None) -> int:
        """Upsert developer distress signals. Best-effort, never raises."""
        if not signals:
            return 0
        try:
            with get_engine().begin() as conn:
                for signal in signals:
                    conn.execute(
                        text(
                            """
                            INSERT INTO developer_distress_signals (
                                developer_name, market, signal_type, stall_count, stall_ratio,
                                mention_count, distress_score, ingest_log_id
                            )
                            VALUES (
                                :developer_name, :market, :signal_type, :stall_count, :stall_ratio,
                                :mention_count, :distress_score, :ingest_log_id
                            )
                            ON CONFLICT (developer_name, market, signal_type)
                            DO UPDATE SET
                                stall_count = EXCLUDED.stall_count,
                                stall_ratio = EXCLUDED.stall_ratio,
                                mention_count = EXCLUDED.mention_count,
                                distress_score = EXCLUDED.distress_score,
                                ingest_log_id = EXCLUDED.ingest_log_id,
                                detected_at = COALESCE(EXCLUDED.detected_at, NOW())
                            """
                        ),
                        {
                            "developer_name": self._normalize_developer_name(signal.get("developer_name", "Unknown")),
                            "market": self._normalize_market(signal.get("market") or market),
                            "signal_type": signal.get("signal_type", "computed"),
                            "stall_count": int(signal.get("stall_count", 0) or 0),
                            "stall_ratio": max(0.0, min(float(signal.get("stall_ratio", 0.0) or 0.0), 1.0)),
                            "mention_count": int(signal.get("mention_count", 0) or 0),
                            "distress_score": max(0.0, min(float(signal.get("distress_score", 0.0) or 0.0), 1.0)),
                            "ingest_log_id": ingest_log_id,
                        },
                    )
        except Exception as exc:
            logger.debug("[DistressedPlugin] persist skipped for {}: {}", market, exc)
            return 0
        return len(signals)

    def run(self, market: str) -> list[ParsedRecord]:
        from utils.distressed_developer import scan_distressed_developers

        market = self._normalize_market(market)

        records: list[ParsedRecord] = []

        # Phase 1: RERA distress scan
        distressed = scan_distressed_developers(
            market=market, min_score=0.0, max_results=20
        )
        for dev in distressed:
            data = {
                "developer_name": dev.developer_name,
                "market": dev.market,
                "total_projects": dev.total_projects,
                "active_projects": dev.active_projects,
                "delayed_projects": dev.delayed_projects,
                "avg_delay_months": dev.avg_delay_months,
                "incomplete_ratio": float(dev.incomplete_ratio),
                "complaint_count": dev.complaint_count,
                "distress_score": float(dev.distress_score),
                "alert_level": dev.alert_level,
                "detected_at": _utc_now_iso(),
            }
            records.append(ParsedRecord(
                entity_type="distressed_opp",
                source_id=f"distressed_{dev.developer_name}_{market}",
                market=market or "all",
                data=data,
            ))

        # Phase 2: BDA e-auctions (non-blocking; empty list if unreachable)
        bda_listings = _fetch_bda_auctions(market)
        for auction in bda_listings:
            pid = auction.get("property_id", "")
            records.append(ParsedRecord(
                entity_type="distressed_opp",
                source_id=f"bda_{pid}" if pid else f"bda_{market}_{datetime.now(timezone.utc).timestamp():.0f}",
                market=market,
                data={
                    "developer_name": "BDA_eAuction",
                    "market": market,
                    "total_projects": 0,
                    "active_projects": 0,
                    "delayed_projects": 0,
                    "avg_delay_months": 0.0,
                    "incomplete_ratio": 0.0,
                    "complaint_count": 0,
                    "distress_score": 0.0,
                    "alert_level": "auction",
                    "property_id": pid,
                    "location": auction.get("location", ""),
                    "area_sqft": auction["area_sqft"],
                    "reserve_price_lakh": auction["reserve_price_lakh"],
                    "auction_date": auction["auction_date"],
                    "property_type": auction["property_type"],
                    "source": auction["source"],
                    "detected_at": _utc_now_iso(),
                },
            ))

        # Phase 3: SARFAESI bank auctions (stub — returns [] until implemented)
        sarfaesi_listings = _search_sarfaesi_auctions(market)
        for prop in sarfaesi_listings:
            records.append(ParsedRecord(
                entity_type="distressed_opp",
                source_id=f"sarfaesi_{prop.get('property_id', 'unk')}_{market}",
                market=market,
                data={
                    "developer_name": "SARFAESI_eAuction",
                    "market": market,
                    "alert_level": "auction",
                    "source": "sarfaesi",
                    "detected_at": _utc_now_iso(),
                    **prop,
                },
            ))

        # Phase 4: stalled RERA projects by developer
        stall_signals = self._detect_rera_stalls(market)
        for signal in stall_signals:
            records.append(ParsedRecord(
                entity_type="distressed_opp",
                source_id=f"rera_stall_{signal['developer_name']}_{market}",
                market=market,
                data={**signal, "detected_at": _utc_now_iso()},
            ))

        # Phase 5: NCLT / insolvency news mentions
        nclt_signals = self._detect_nclt_from_news(market)
        for signal in nclt_signals:
            records.append(ParsedRecord(
                entity_type="distressed_opp",
                source_id=f"nclt_{signal['developer_name']}_{market}",
                market=market,
                data={**signal, "detected_at": _utc_now_iso()},
            ))

        raw_signals = stall_signals + nclt_signals
        self._persist_distress_signals(market, raw_signals)
        computed_signals = self._compute_and_persist_scores(market, raw_signals)
        for signal in computed_signals:
            records.append(ParsedRecord(
                entity_type="distressed_opp",
                source_id=f"computed_{signal['developer_name']}_{market}",
                market=market,
                data={**signal, "detected_at": _utc_now_iso()},
            ))

        logger.info(
            "[DistressedPlugin] {} records for {} ({} distressed, {} BDA, {} SARFAESI, {} RERA stalls, {} NCLT, {} computed)",
            len(records), market, len(distressed), len(bda_listings), len(sarfaesi_listings), len(stall_signals), len(nclt_signals), len(computed_signals),
        )
        return records
