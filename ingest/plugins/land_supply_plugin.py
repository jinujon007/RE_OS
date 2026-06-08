"""
RE_OS — Land Supply Scout Plugin (Sprint 73 — GATE-73)

Three-phase land supply pipeline estimator:

1. RERA pipeline  — pre-registration/new/registered projects not yet completed.
2. KIADB tenders  — best-effort fetch from KIADB WordPress REST API.
3. BDA/BMRDA news — existing news_articles table scan for layout/acquisition
                    mentions with unit count extraction.

All phases produce ParsedRecord(entity_type='supply_pipeline') entries.
The IngestEngine upserts these into the supply_pipeline table on
canonical_id to prevent duplicates across runs.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text

from ingest.base import DataPlugin, ParsedRecord, ValidationResult
from utils.db import get_engine

__all__ = ["LandSupplyPlugin"]

_KIADB_API_URL = "https://kiadb.in/wp-json/wp/v2/posts?categories=tenders&per_page=20"
_SCRAPING_HEADERS = {
    "User-Agent": "RE_OS/1.0 (market-intel-system)",
    "Accept": "application/json",
}

_BDA_NEWS_KEYWORDS = [
    "bda layout", "bda site", "bmrda", "kiadb acquisition",
    "kiadb land", "bda allotment", "bda e-auction",
    "layout formation", "new layout", "residential layout",
    "industrial area", "kiadb plot",
]


class LandSupplyPlugin(DataPlugin):
    """Land supply pipeline estimator across three sources.

    Phase 1 — RERA pipeline: projects in pre-registration/new/registered
              status with future completion dates.
    Phase 2 — KIADB tenders: WordPress REST API fetch (best-effort).
    Phase 3 — BDA/BMRDA news: news_articles table scan.
    """

    plugin_id = "land_supply"
    source_id = "land_supply_scout"

    def run(self, market: str) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []

        phase1 = self._rera_pipeline_phase(market)
        records.extend(phase1)

        phase2 = self._scrape_kiadb_tenders(market)
        records.extend(phase2)

        phase3 = self._detect_supply_from_news(market)
        records.extend(phase3)

        logger.info(
            "[LandSupplyPlugin] {} — {} RERA + {} KIADB + {} news = {} records",
            market, len(phase1), len(phase2), len(phase3), len(records),
        )
        return records

    def validate(self, record: ParsedRecord) -> ValidationResult:
        errors = []
        if not record.data.get("market"):
            errors.append("market required")
        if not record.data.get("source"):
            errors.append("source required")
        return ValidationResult(valid=not errors, errors=errors)

    # ── Phase 1: RERA pipeline ──────────────────────────────────────────────

    def _rera_pipeline_phase(self, market: str) -> list[ParsedRecord]:
        """Query rera_projects in pre-registration/new/registered status."""
        market_like = f"%{market}%"
        try:
            with get_engine().connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT
                            rp.id::text AS record_id,
                            COALESCE(rp.project_name, 'Unknown') AS project_name,
                            COALESCE(d.name, rp.developer_name, 'Unknown') AS developer_name,
                            rp.total_units,
                            rp.launch_date,
                            rp.expected_completion_date,
                            rp.status
                        FROM rera_projects rp
                        LEFT JOIN developers d ON d.id = rp.developer_id
                        LEFT JOIN micro_markets mm ON mm.id = rp.micro_market_id
                        WHERE LOWER(mm.name) ILIKE :market
                          AND LOWER(rp.status) IN ('pre-registration', 'new', 'registered')
                          AND (
                              rp.expected_completion_date IS NULL
                              OR rp.expected_completion_date > NOW()
                          )
                        ORDER BY rp.expected_completion_date ASC NULLS LAST
                        LIMIT 100
                    """),
                    {"market": market_like},
                ).fetchall()
        except Exception as exc:
            logger.debug("[LandSupplyPlugin] RERA pipeline phase failed for {}: {}", market, exc)
            return []

        records: list[ParsedRecord] = []
        for row in rows:
            record_id, project_name, developer_name, units, launch_date, completion_date, status = row
            units_int = int(units) if units else 0
            comp_year = completion_date.year if completion_date else None
            data = {
                "project_name": str(project_name),
                "developer_name": str(developer_name),
                "estimated_units": units_int,
                "source": "rera_pipeline",
                "market": market,
                "status": str(status) if status else None,
                "approval_date": str(launch_date) if launch_date else None,
                "expected_completion_year": comp_year,
            }
            records.append(ParsedRecord(
                entity_type="supply_pipeline",
                source_id=f"rera_{record_id}",
                market=market,
                data=data,
                confidence=0.8,
            ))
        return records

    # ── Phase 2: KIADB tenders ──────────────────────────────────────────────

    def _scrape_kiadb_tenders(self, market: str) -> list[ParsedRecord]:
        """Fetch KIADB WordPress REST API tenders filtered by market keyword."""
        try:
            req = urllib.request.Request(
                _KIADB_API_URL,
                headers=_SCRAPING_HEADERS,
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = json.loads(resp.read())
        except Exception as exc:
            logger.debug("[LandSupplyPlugin] KIADB tender fetch failed (non-fatal): {}", exc)
            return []

        posts = raw if isinstance(raw, list) else raw.get("data", raw.get("posts", []))
        records: list[ParsedRecord] = []
        market_lower = market.lower()

        for post in (posts or []):
            title = str(post.get("title", {}).get("rendered", "") or post.get("title", ""))
            content = str(post.get("content", {}).get("rendered", "") or post.get("content", ""))
            combined = (title + " " + content).lower()

            if market_lower not in combined:
                continue

            # Extract hectares or acres
            ha_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hectares?|ha)", combined)
            acres_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:acres?|acre)", combined)
            estimated_acres = None
            if ha_match:
                estimated_acres = round(float(ha_match.group(1)) * 2.47105, 2)
            elif acres_match:
                estimated_acres = round(float(acres_match.group(1)), 2)

            data = {
                "project_name": str(title)[:200] if title else "KIADB Tender",
                "developer_name": "KIADB",
                "estimated_units": 0,
                "estimated_acres": estimated_acres,
                "source": "kiadb_tender",
                "market": market,
                "raw_snippet": str(title)[:300],
            }
            cid = f"kiadb_{hash(str(post.get('id', title))) % 10**8}"
            records.append(ParsedRecord(
                entity_type="supply_pipeline",
                source_id=cid,
                market=market,
                data=data,
                confidence=0.5,
            ))

        logger.info("[LandSupplyPlugin] {} KIADB tenders for {}", len(records), market)
        return records

    # ── Phase 3: BDA/BMRDA news detection ───────────────────────────────────

    def _detect_supply_from_news(self, market: str) -> list[ParsedRecord]:
        """Scan news_articles for BDA layout / BMRDA / KIADB acquisition mentions."""
        market_like = f"%{market}%"
        keyword_conditions = " OR ".join(
            f"LOWER(na.title) LIKE :kw{i} OR LOWER(na.content) LIKE :kw{i}"
            for i in range(len(_BDA_NEWS_KEYWORDS))
        )
        params: dict[str, Any] = {}
        for i, kw in enumerate(_BDA_NEWS_KEYWORDS):
            params[f"kw{i}"] = f"%{kw}%"

        try:
            with get_engine().connect() as conn:
                rows = conn.execute(
                    text(f"""
                        SELECT na.id::text, na.title, na.content, na.published_at
                        FROM news_articles na
                        WHERE ({keyword_conditions})
                          AND (na.title ILIKE :market OR na.content ILIKE :market)
                          AND na.created_at >= NOW() - INTERVAL '90 days'
                        ORDER BY na.created_at DESC
                        LIMIT 30
                    """),
                    {**params, "market": market_like},
                ).fetchall()
        except Exception as exc:
            logger.debug("[LandSupplyPlugin] BDA news detection failed for {}: {}", market, exc)
            return []

        records: list[ParsedRecord] = []
        for row in rows:
            art_id, title, content, published_at = row
            combined = (title or "") + " " + (content or "")

            # Extract unit counts: 2-5 digit number + units/plots/homes/villas/apartments/flats
            unit_match = re.search(
                r"(\d{2,5})\s*(?:units?|plots?|homes?|villas?|apartments?|flats?)",
                combined, re.IGNORECASE,
            )
            units = int(unit_match.group(1)) if unit_match else 0

            # Extract acres for layout-area estimation
            acres_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:acres?|acre)", combined, re.IGNORECASE)
            acres = round(float(acres_match.group(1)), 2) if acres_match else None

            data = {
                "project_name": str(title)[:200] if title else "BDA/BMRDA Supply",
                "developer_name": "BDA",
                "estimated_units": units,
                "estimated_acres": acres,
                "source": "bda_news",
                "market": market,
                "approval_date": str(published_at)[:10] if published_at else None,
                "raw_snippet": str(title)[:300] if title else "",
            }
            records.append(ParsedRecord(
                entity_type="supply_pipeline",
                source_id=f"bda_news_{art_id}",
                market=market,
                data=data,
                confidence=0.5,
            ))
        return records
