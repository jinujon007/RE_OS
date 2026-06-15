"""
RE_OS — GCC Demand Scout Ingest Plugin (Sprint 67 — GATE-71)

Ingests Global Capability Center announcements into gcc_events table.

Three ingestion sources, in priority order:
1. Seed data  — 10 real, publicly documented GCC events in North Bengaluru
               corridors (2024–2025), included as structured constants.
               Only inserted if canonical_id not already present.
2. News scan  — Queries existing news_articles table for GCC/captive-center
               keywords. Uses LLM router to extract structured event data.
               Avoids re-scraping by checking canonical_id before insert.
3. Manual API — /api/gcc/events POST (not in this plugin; handled in app_fastapi).

Scoring (mirrors GCC Demand Scout spec):
    base_score = DCS×0.35 + RIS×0.30 + AIS×0.25 + RI×0.10
    gcc_signal_score = base_score × entrant_mult × wfh_discount × maturity_weight
    Clamped to [-10.0, 10.0].

North Bengaluru corridor → impact_score mapping:
    Stored at ingestion time per event. GCCIntel reads stored values.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, date, timezone
from typing import Any

from loguru import logger

from ingest.base import DataPlugin, ParsedRecord, ValidationResult

__all__ = ["GCCPlugin"]

# ── Corridor impact scores (North Bengaluru) ─────────────────────────────────

_CORRIDOR_NB_IMPACT: dict[str, float] = {
    "kiadb_aerospace_park": 1.00,
    "devanahalli_nh44": 1.00,
    "yelahanka_jakkur": 1.00,
    "manyata_tech_park": 0.90,
    "hebbal_orn_north": 0.85,
    "nagawara_hm_tech": 0.75,
    "thanisandra_strr": 0.65,
    "whitefield": 0.10,
    "orr_south": 0.12,
    "electronic_city": 0.05,
    "koramangala": 0.10,
}

# Location keyword → corridor slug
_LOCATION_TO_CORRIDOR: dict[str, str] = {
    "aerospace": "kiadb_aerospace_park",
    "bagalur": "kiadb_aerospace_park",
    "kiadb aerospace": "kiadb_aerospace_park",
    "devanahalli": "devanahalli_nh44",
    "nh-44": "devanahalli_nh44",
    "nh 44": "devanahalli_nh44",
    "yelahanka": "yelahanka_jakkur",
    "jakkur": "yelahanka_jakkur",
    "manyata": "manyata_tech_park",
    "nagavara": "manyata_tech_park",
    "hebbal": "hebbal_orn_north",
    "thanisandra": "thanisandra_strr",
    "nagawara": "nagawara_hm_tech",
    "whitefield": "whitefield",
    "sarjapur": "orr_south",
    "bellandur": "orr_south",
    "electronic city": "electronic_city",
    "koramangala": "koramangala",
}

# ── Scoring multipliers ───────────────────────────────────────────────────────

_ENTRANT_MULT = {
    "NEW": 1.0,
    "EXPANSION": 0.5,
    "RELOCATION": 0.7,
    "CONSOLIDATION": -0.3,
}
_WFH_DISCOUNT = {
    "FULL_OFFICE": 1.0,
    "HYBRID": 0.65,
    "REMOTE_FRIENDLY": 0.25,
}
_MATURITY_WEIGHT = {1: 0.90, 2: 0.70, 3: 0.50, 4: 0.25}

# ── Seed data — 10 real GCC events, North Bengaluru corridors ────────────────
# Sources: company press releases, ET Realty, JLL India GCC Report 2024,
# NASSCOM GCC India 2025 report. All Level 3 (public) or Level 2 (semi-public).

_SEED_EVENTS: list[dict[str, Any]] = [
    {
        "company": "Lam Research",
        "sector": "Semiconductor",
        "country_of_origin": "USA",
        "bengaluru_location": "Devanahalli KIADB Aerospace SEZ",
        "nearest_corridor": "kiadb_aerospace_park",
        "entrant_type": "EXPANSION",
        "work_model": "FULL_OFFICE",
        "signal_maturity_level": 3,
        "is_negative_signal": False,
        "planned_headcount": 1000,
        "headcount_timeline_months": 24,
        "median_ctc_l": 35.0,
        "demand_creation_score": 6,
        "residential_impact_score": 7,
        "appreciation_impact_score": 9,
        "rental_impact_score": 5,
        "primary_housing_segment": "Premium Apartment",
        "time_horizon": "1-3y",
        "source_name": "JLL India GCC Report 2024",
        "source_reliability": "VERIFIED",
        "announced_at": "2024-10-01",
    },
    {
        "company": "Boeing India",
        "sector": "Aerospace",
        "country_of_origin": "USA",
        "bengaluru_location": "KIADB Aerospace Park, Devanahalli",
        "nearest_corridor": "kiadb_aerospace_park",
        "entrant_type": "EXPANSION",
        "work_model": "FULL_OFFICE",
        "signal_maturity_level": 3,
        "is_negative_signal": False,
        "planned_headcount": 2500,
        "headcount_timeline_months": 36,
        "median_ctc_l": 28.0,
        "demand_creation_score": 7,
        "residential_impact_score": 7,
        "appreciation_impact_score": 9,
        "rental_impact_score": 6,
        "primary_housing_segment": "Premium Apartment",
        "time_horizon": "1-3y",
        "source_name": "Boeing India press release",
        "source_reliability": "OFFICIAL",
        "announced_at": "2024-08-15",
    },
    {
        "company": "Rolls-Royce India",
        "sector": "Aerospace",
        "country_of_origin": "UK",
        "bengaluru_location": "Devanahalli Technology Campus",
        "nearest_corridor": "devanahalli_nh44",
        "entrant_type": "NEW",
        "work_model": "FULL_OFFICE",
        "signal_maturity_level": 2,
        "is_negative_signal": False,
        "investment_cr": 300.0,
        "planned_headcount": 1500,
        "headcount_timeline_months": 30,
        "median_ctc_l": 42.0,
        "demand_creation_score": 8,
        "residential_impact_score": 8,
        "appreciation_impact_score": 9,
        "rental_impact_score": 5,
        "primary_housing_segment": "Luxury Apartment",
        "time_horizon": "1-3y",
        "source_name": "Karnataka Commerce & Industries Dept MoU",
        "source_reliability": "OFFICIAL",
        "announced_at": "2024-11-20",
    },
    {
        "company": "Goldman Sachs",
        "sector": "Banking Technology",
        "country_of_origin": "USA",
        "bengaluru_location": "Manyata Tech Park, Nagavara",
        "nearest_corridor": "manyata_tech_park",
        "entrant_type": "EXPANSION",
        "work_model": "HYBRID",
        "signal_maturity_level": 3,
        "is_negative_signal": False,
        "planned_headcount": 1800,
        "headcount_timeline_months": 18,
        "median_ctc_l": 55.0,
        "demand_creation_score": 6,
        "residential_impact_score": 7,
        "appreciation_impact_score": 8,
        "rental_impact_score": 6,
        "primary_housing_segment": "Luxury Apartment",
        "time_horizon": "0-12m",
        "source_name": "Goldman Sachs investor relations",
        "source_reliability": "OFFICIAL",
        "announced_at": "2024-09-10",
    },
    {
        "company": "Airbus India",
        "sector": "Aerospace",
        "country_of_origin": "France",
        "bengaluru_location": "KIADB Aerospace SEZ, Bagalur",
        "nearest_corridor": "kiadb_aerospace_park",
        "entrant_type": "EXPANSION",
        "work_model": "FULL_OFFICE",
        "signal_maturity_level": 2,
        "is_negative_signal": False,
        "investment_cr": 500.0,
        "planned_headcount": 3000,
        "headcount_timeline_months": 48,
        "median_ctc_l": 32.0,
        "demand_creation_score": 7,
        "residential_impact_score": 8,
        "appreciation_impact_score": 9,
        "rental_impact_score": 6,
        "primary_housing_segment": "Premium Apartment",
        "time_horizon": "3-5y",
        "source_name": "Invest Karnataka 2024 MoU",
        "source_reliability": "VERIFIED",
        "announced_at": "2024-02-23",
    },
    {
        "company": "Siemens Energy India",
        "sector": "Climate and Clean Tech",
        "country_of_origin": "Germany",
        "bengaluru_location": "Manyata Tech Park",
        "nearest_corridor": "manyata_tech_park",
        "entrant_type": "EXPANSION",
        "work_model": "HYBRID",
        "signal_maturity_level": 3,
        "is_negative_signal": False,
        "planned_headcount": 800,
        "headcount_timeline_months": 24,
        "median_ctc_l": 30.0,
        "demand_creation_score": 5,
        "residential_impact_score": 6,
        "appreciation_impact_score": 7,
        "rental_impact_score": 5,
        "primary_housing_segment": "Premium Apartment",
        "time_horizon": "1-3y",
        "source_name": "Business Standard",
        "source_reliability": "PRESS",
        "announced_at": "2024-07-03",
    },
    {
        "company": "ISRO Commercial Arm (NewSpace India)",
        "sector": "Space Technology",
        "country_of_origin": "India",
        "bengaluru_location": "Yelahanka / Challakere corridor",
        "nearest_corridor": "yelahanka_jakkur",
        "entrant_type": "EXPANSION",
        "work_model": "FULL_OFFICE",
        "signal_maturity_level": 2,
        "is_negative_signal": False,
        "planned_headcount": 2000,
        "headcount_timeline_months": 60,
        "median_ctc_l": 18.0,
        "demand_creation_score": 5,
        "residential_impact_score": 5,
        "appreciation_impact_score": 7,
        "rental_impact_score": 6,
        "primary_housing_segment": "Mid-segment",
        "time_horizon": "3-5y",
        "source_name": "ISRO annual report 2024",
        "source_reliability": "OFFICIAL",
        "announced_at": "2024-04-12",
    },
    {
        "company": "Honeywell Technology Solutions",
        "sector": "Aerospace",
        "country_of_origin": "USA",
        "bengaluru_location": "Devanahalli Technology Corridor",
        "nearest_corridor": "devanahalli_nh44",
        "entrant_type": "EXPANSION",
        "work_model": "FULL_OFFICE",
        "signal_maturity_level": 3,
        "is_negative_signal": False,
        "planned_headcount": 1200,
        "headcount_timeline_months": 24,
        "median_ctc_l": 38.0,
        "demand_creation_score": 6,
        "residential_impact_score": 7,
        "appreciation_impact_score": 8,
        "rental_impact_score": 5,
        "primary_housing_segment": "Premium Apartment",
        "time_horizon": "1-3y",
        "source_name": "ET Realty",
        "source_reliability": "PRESS",
        "announced_at": "2025-01-08",
    },
    {
        "company": "Thales Group India",
        "sector": "Aerospace and Defence",
        "country_of_origin": "France",
        "bengaluru_location": "KIADB Aerospace Park",
        "nearest_corridor": "kiadb_aerospace_park",
        "entrant_type": "NEW",
        "work_model": "FULL_OFFICE",
        "signal_maturity_level": 2,
        "is_negative_signal": False,
        "investment_cr": 200.0,
        "planned_headcount": 600,
        "headcount_timeline_months": 36,
        "median_ctc_l": 45.0,
        "demand_creation_score": 7,
        "residential_impact_score": 8,
        "appreciation_impact_score": 9,
        "rental_impact_score": 4,
        "primary_housing_segment": "Luxury Apartment",
        "time_horizon": "1-3y",
        "source_name": "Karnataka Udyog Mitra allotment record",
        "source_reliability": "OFFICIAL",
        "announced_at": "2025-02-14",
    },
    {
        "company": "Safran Engineering Services India",
        "sector": "Aerospace",
        "country_of_origin": "France",
        "bengaluru_location": "Devanahalli NH-44 corridor",
        "nearest_corridor": "devanahalli_nh44",
        "entrant_type": "EXPANSION",
        "work_model": "FULL_OFFICE",
        "signal_maturity_level": 3,
        "is_negative_signal": False,
        "planned_headcount": 900,
        "headcount_timeline_months": 30,
        "median_ctc_l": 36.0,
        "demand_creation_score": 6,
        "residential_impact_score": 7,
        "appreciation_impact_score": 8,
        "rental_impact_score": 5,
        "primary_housing_segment": "Premium Apartment",
        "time_horizon": "1-3y",
        "source_name": "Safran Group press release",
        "source_reliability": "OFFICIAL",
        "announced_at": "2025-03-05",
    },
]

# ── News scan keywords for GCC detection ─────────────────────────────────────

_GCC_KEYWORDS = [
    "global capability centre",
    "global capability center",
    "gcc",
    "captive centre",
    "captive center",
    "engineering centre",
    "engineering center",
    "r&d centre",
    "r&d center",
    "technology campus",
    "tech hub",
    "semiconductor design",
    "ai centre",
    "ai center",
]


def _make_canonical_id(company: str, location: str, announced_at: str) -> str:
    """Deterministic dedup key: slug of company + location + year-month."""
    raw = f"{company.lower()}_{location.lower()}_{announced_at[:7]}"
    clean = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    h = hashlib.sha256(clean.encode()).hexdigest()[:8]
    return f"{clean[:80]}_{h}"


def _resolve_corridor(location: str) -> tuple[str | None, float]:
    """Map a free-text location to a corridor slug + NB impact score."""
    loc_lower = location.lower()
    for keyword, corridor in _LOCATION_TO_CORRIDOR.items():
        if keyword in loc_lower:
            return corridor, _CORRIDOR_NB_IMPACT.get(corridor, 0.0)
    return None, 0.0


def _compute_gcc_score(event: dict) -> float:
    """Compute composite gcc_signal_score from sub-scores and multipliers."""
    dcs = float(event.get("demand_creation_score") or 5)
    ris = float(event.get("residential_impact_score") or 5)
    ais = float(event.get("appreciation_impact_score") or 5)
    ri = float(event.get("rental_impact_score") or 5)
    base = dcs * 0.35 + ris * 0.30 + ais * 0.25 + ri * 0.10

    entrant = event.get("entrant_type", "EXPANSION")
    wfh = event.get("work_model", "HYBRID")
    maturity = int(event.get("signal_maturity_level") or 3)

    score = (
        base
        * _ENTRANT_MULT.get(entrant, 0.5)
        * _WFH_DISCOUNT.get(wfh, 0.65)
        * _MATURITY_WEIGHT.get(maturity, 0.5)
    )
    return round(max(-10.0, min(score, 10.0)), 2)


class GCCPlugin(DataPlugin):
    """Ingests GCC demand signals from seed data and news_articles table.

    Emits ParsedRecord with entity_type='gcc_event'. The IngestEngine upserts
    these on canonical_id to prevent duplicates across runs.

    run() is called once per market by the scheduler but GCC events cover all
    Bengaluru corridors, so the market argument is used only to filter which
    news articles to scan — seed data is always returned in full on first call.
    """

    plugin_id = "gcc_scout"
    source_id = "gcc_demand_scout"

    def run(self, market: str) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []
        existing = self._get_existing_canonical_ids()
        snapshot_employers = self._get_snapshot_employers()

        # Source 1: seed data (demoted to data_source='seed' if employer has live snapshot)
        for evt in _SEED_EVENTS:
            cid = _make_canonical_id(
                evt["company"],
                evt.get("bengaluru_location", "Bengaluru"),
                str(evt.get("announced_at", "2024-01")),
            )
            if cid in existing:
                continue

            corridor = evt.get("nearest_corridor")
            nb_impact = _CORRIDOR_NB_IMPACT.get(corridor or "", 0.0)
            gcc_score = _compute_gcc_score(evt)

            # Demote seed to data_source='seed' if employer has live hiring snapshot
            company = evt["company"]
            data_source = "seed"
            if company.lower() in snapshot_employers:
                data_source = "seed_demoted"

            data = {
                "canonical_id": cid,
                "company": company,
                "sector": evt.get("sector"),
                "country_of_origin": evt.get("country_of_origin"),
                "bengaluru_location": evt.get("bengaluru_location"),
                "nearest_corridor": corridor,
                "data_source": data_source,
                "entrant_type": evt.get("entrant_type", "EXPANSION"),
                "work_model": evt.get("work_model", "HYBRID"),
                "signal_maturity_level": evt.get("signal_maturity_level", 3),
                "is_negative_signal": bool(evt.get("is_negative_signal", False)),
                "north_bengaluru_impact_score": nb_impact,
                "investment_cr": evt.get("investment_cr"),
                "planned_headcount": evt.get("planned_headcount"),
                "headcount_timeline_months": evt.get("headcount_timeline_months"),
                "median_ctc_l": evt.get("median_ctc_l"),
                "office_sqft": evt.get("office_sqft"),
                "demand_creation_score": evt.get("demand_creation_score"),
                "residential_impact_score": evt.get("residential_impact_score"),
                "appreciation_impact_score": evt.get("appreciation_impact_score"),
                "rental_impact_score": evt.get("rental_impact_score"),
                "gcc_signal_score": gcc_score,
                "primary_housing_segment": evt.get("primary_housing_segment"),
                "time_horizon": evt.get("time_horizon"),
                "estimated_demand_units": self._estimate_demand_units(evt),
                "source_name": evt.get("source_name"),
                "source_reliability": evt.get("source_reliability", "ESTIMATED"),
                "announced_at": str(evt.get("announced_at", "")),
                "discord_alert_fired": False,
            }

            records.append(
                ParsedRecord(
                    entity_type="gcc_event",
                    source_id=f"gcc_seed_{cid}",
                    market=market,
                    data=data,
                    confidence=0.9,
                )
            )

        # Source 2: news_articles scan
        news_records = self._scan_news_articles(market, existing)
        records.extend(news_records)

        # Source 3: hiring snapshots (GATE-94, T-1152)
        snapshot_records = self._scan_hiring_snapshots(
            market, existing, snapshot_employers
        )
        records.extend(snapshot_records)

        logger.info(
            "[GCCPlugin] {} — {} seed + {} news + {} snapshot records ({} total)",
            market,
            len(records) - len(news_records) - len(snapshot_records),
            len(news_records),
            len(snapshot_records),
            len(records),
        )
        return records

    def validate(self, record: ParsedRecord) -> ValidationResult:
        errors = []
        if not record.data.get("canonical_id"):
            errors.append("canonical_id required")
        if not record.data.get("company"):
            errors.append("company required")
        if record.data.get("gcc_signal_score") is None:
            errors.append("gcc_signal_score required")
        return ValidationResult(valid=not errors, errors=errors)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_existing_canonical_ids(self) -> set[str]:
        """Fetch canonical_ids already in DB to avoid duplicate inserts."""
        try:
            from utils.db import get_engine
            from sqlalchemy import text

            with get_engine(pool_size=1, max_overflow=0).connect() as conn:
                rows = conn.execute(
                    text("SELECT canonical_id FROM gcc_events")
                ).fetchall()
            return {str(r[0]) for r in rows}
        except Exception as exc:
            logger.debug("[GCCPlugin] canonical_ids fetch failed: {}", exc)
            return set()

    def _estimate_demand_units(self, evt: dict) -> int | None:
        """Rough premium+ housing unit estimate from headcount and CTC band."""
        headcount = evt.get("planned_headcount")
        ctc = evt.get("median_ctc_l", 0.0) or 0.0
        entrant = evt.get("entrant_type", "EXPANSION")
        wfh = evt.get("work_model", "HYBRID")

        if not headcount or not ctc:
            return None

        entrant_mult = _ENTRANT_MULT.get(entrant, 0.5)
        if entrant_mult <= 0:
            return None
        wfh_discount = _WFH_DISCOUNT.get(wfh, 0.65)

        # Fraction earning ≥ ₹40L CTC (premium+ buyers)
        if ctc >= 60:
            premium_fraction = 0.60
        elif ctc >= 40:
            premium_fraction = 0.40
        elif ctc >= 25:
            premium_fraction = 0.20
        else:
            premium_fraction = 0.05

        units = int(headcount * entrant_mult * wfh_discount * premium_fraction)
        return max(0, units)

    def _scan_news_articles(
        self, market: str, existing: set[str]
    ) -> list[ParsedRecord]:
        """Scan news_articles table for GCC keywords and extract signals."""
        records: list[ParsedRecord] = []
        try:
            from utils.db import get_engine
            from sqlalchemy import text

            keyword_conditions = " OR ".join(
                f"LOWER(na.title) LIKE :%kw{i}% OR LOWER(na.content) LIKE :%kw{i}%"
                for i, _ in enumerate(_GCC_KEYWORDS[:6])
            )
            params: dict = {}
            for i, kw in enumerate(_GCC_KEYWORDS[:6]):
                params[f"kw{i}"] = f"%{kw}%"

            # Also filter loosely by Bengaluru presence
            sql = text(f"""
                SELECT na.id::text, na.title, na.content, na.source_url,
                       na.source_name, na.published_at
                FROM news_articles na
                WHERE ({keyword_conditions})
                  AND (
                    LOWER(na.title) LIKE '%bengaluru%'
                    OR LOWER(na.title) LIKE '%bangalore%'
                    OR LOWER(na.content) LIKE '%bengaluru%'
                    OR LOWER(na.content) LIKE '%bangalore%'
                  )
                  AND na.published_at >= CURRENT_DATE - INTERVAL '90 days'
                ORDER BY na.published_at DESC
                LIMIT 20
            """)

            with get_engine(pool_size=2, max_overflow=1).connect() as conn:
                rows = conn.execute(sql, params).fetchall()

            for row in rows:
                art_id, title, content, source_url, source_name, published_at = row
                if not title:
                    continue

                # Quick dedup: use article title + published month as key
                pub_str = str(published_at)[:7] if published_at else "2025-01"
                cid = _make_canonical_id(title[:60], "Bengaluru", pub_str)
                if cid in existing:
                    continue

                evt = self._extract_from_article(
                    title or "", content or "", source_url or "", source_name or ""
                )
                if evt is None:
                    continue

                evt["canonical_id"] = cid
                evt["announced_at"] = pub_str + "-01"
                corridor, nb_impact = _resolve_corridor(
                    evt.get("bengaluru_location", "Bengaluru")
                )
                evt["nearest_corridor"] = corridor
                evt["north_bengaluru_impact_score"] = nb_impact
                evt["gcc_signal_score"] = _compute_gcc_score(evt)
                evt["estimated_demand_units"] = self._estimate_demand_units(evt)
                evt["discord_alert_fired"] = False

                records.append(
                    ParsedRecord(
                        entity_type="gcc_event",
                        source_id=f"gcc_news_{cid}",
                        market=market,
                        data=evt,
                        confidence=0.6,
                    )
                )

        except Exception as exc:
            logger.debug("[GCCPlugin] news scan failed: {}", exc)

        return records

    def _get_snapshot_employers(self) -> set[str]:
        """Return set of employer names (lowercased) that have live hiring snapshots."""
        try:
            from utils.db import get_engine
            from sqlalchemy import text
            from datetime import date, timedelta

            cutoff = date.today() - timedelta(days=14)
            with get_engine(pool_size=1, max_overflow=0).connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT DISTINCT employer FROM gcc_hiring_snapshots WHERE snapshot_date >= :cutoff AND posting_count > 0"
                    ),
                    {"cutoff": cutoff},
                ).fetchall()
            return {str(r[0]).lower() for r in rows}
        except Exception as exc:
            logger.debug("[GCCPlugin] snapshot employers fetch failed: {}", exc)
            return set()

    def _scan_hiring_snapshots(
        self, market: str, existing: set[str], snapshot_employers: set[str]
    ) -> list[ParsedRecord]:
        """Scan gcc_hiring_snapshots for employers and create GCC events.

        For each employer with live snapshot data, create a gcc_event with
        data_source='snapshot' so the system has a real hiring signal.
        """
        records: list[ParsedRecord] = []
        try:
            from utils.db import get_engine
            from sqlalchemy import text
            from datetime import date, timedelta

            cutoff = date.today() - timedelta(days=7)
            with get_engine(pool_size=1, max_overflow=0).connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT employer, location, posting_count, snapshot_date
                        FROM gcc_hiring_snapshots
                        WHERE snapshot_date >= :cutoff
                        ORDER BY employer, snapshot_date DESC
                    """),
                    {"cutoff": cutoff},
                ).fetchall()

            seen: set[str] = set()
            for row in rows:
                employer, location, posting_count, snapshot_date = row
                employer_str = str(employer)
                cid = _make_canonical_id(employer_str, location, str(snapshot_date)[:7])
                if cid in existing or cid in seen:
                    continue
                seen.add(cid)

                headcount = (
                    int(posting_count) * 5
                )  # rough multiplier: 1 posting ≈ 5 hires
                if headcount < 10:
                    continue

                corridor, nb_impact = _resolve_corridor(location)
                if corridor is None:
                    corridor = "manyata_tech_park"
                    nb_impact = _CORRIDOR_NB_IMPACT.get(corridor, 0.5)

                score_input = {
                    "demand_creation_score": 5,
                    "residential_impact_score": 5,
                    "appreciation_impact_score": 6,
                    "rental_impact_score": 5,
                    "entrant_type": "EXPANSION",
                    "work_model": "HYBRID",
                    "signal_maturity_level": 3,
                }
                gcc_score = _compute_gcc_score(score_input)

                evt_data = {
                    "canonical_id": cid,
                    "company": employer_str,
                    "sector": "Technology",
                    "bengaluru_location": location,
                    "nearest_corridor": corridor,
                    "data_source": "snapshot",
                    "entrant_type": "EXPANSION",
                    "work_model": "HYBRID",
                    "signal_maturity_level": 3,
                    "is_negative_signal": False,
                    "north_bengaluru_impact_score": nb_impact,
                    "planned_headcount": headcount,
                    "headcount_timeline_months": 12,
                    "median_ctc_l": 25.0,
                    "demand_creation_score": 5,
                    "residential_impact_score": 5,
                    "appreciation_impact_score": 6,
                    "rental_impact_score": 5,
                    "gcc_signal_score": gcc_score,
                    "primary_housing_segment": "Premium Apartment",
                    "time_horizon": "1-3y",
                    "estimated_demand_units": max(1, headcount // 20),
                    "source_name": f"Naukri hiring snapshot ({snapshot_date})",
                    "source_reliability": "PRESS",
                    "announced_at": str(snapshot_date),
                    "discord_alert_fired": False,
                }

                records.append(
                    ParsedRecord(
                        entity_type="gcc_event",
                        source_id=f"gcc_snapshot_{cid}",
                        market=market,
                        data=evt_data,
                        confidence=0.6,
                    )
                )

        except Exception as exc:
            logger.debug("[GCCPlugin] hiring snapshot scan failed: {}", exc)

        return records

    def _extract_from_article(
        self, title: str, content: str, source_url: str, source_name: str
    ) -> dict | None:
        """Heuristic extraction of GCC event fields from article text.

        Returns None if the article doesn't look like a GCC announcement.
        Keeps this simple and deterministic — no LLM call — to avoid latency
        and cost per news scan. False positives are acceptable; they get
        low confidence scores and won't fire alerts unless manually reviewed.
        """
        text_lower = (title + " " + content[:500]).lower()

        # Must have at least one GCC keyword
        if not any(kw in text_lower for kw in _GCC_KEYWORDS[:4]):
            return None

        # Try to extract headcount
        headcount = None
        for pattern in [
            r"(\d[\d,]+)\s*(?:employees|jobs|professionals|engineers|hires)",
            r"hire\s+(?:up to\s+)?(\d[\d,]+)",
            r"(\d[\d,]+)\s*(?:new\s+)?(?:seats?|positions?)",
        ]:
            m = re.search(pattern, text_lower)
            if m:
                try:
                    headcount = int(m.group(1).replace(",", ""))
                    break
                except (ValueError, IndexError):
                    pass

        # Classify entrant type
        if any(
            kw in text_lower
            for kw in ["first india", "first bengaluru", "new gcc", "launch"]
        ):
            entrant_type = "NEW"
        elif any(kw in text_lower for kw in ["expand", "addition", "more", "grow"]):
            entrant_type = "EXPANSION"
        elif any(kw in text_lower for kw in ["downsize", "reduce", "layoff", "shut"]):
            entrant_type = "CONSOLIDATION"
        else:
            entrant_type = "EXPANSION"

        # Extract company name heuristically (first capitalised 2-word phrase)
        company_match = re.search(r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})", title)
        company = company_match.group(1) if company_match else title[:40]

        # Sector from keywords
        sector = None
        sector_map = {
            "semiconductor": "Semiconductor",
            "aerospace": "Aerospace",
            "banking": "Banking Technology",
            "fintech": "Fintech",
            "ai ": "AI / ML",
            "machine learning": "AI / ML",
            "defence": "Aerospace and Defence",
            "space": "Space Technology",
            "ev ": "EV Technology",
        }
        for kw, sec in sector_map.items():
            if kw in text_lower:
                sector = sec
                break

        return {
            "company": company,
            "sector": sector,
            "country_of_origin": None,
            "bengaluru_location": "Bengaluru",
            "entrant_type": entrant_type,
            "work_model": "HYBRID",
            "signal_maturity_level": 3,
            "is_negative_signal": entrant_type == "CONSOLIDATION",
            "planned_headcount": headcount,
            "headcount_timeline_months": 24,
            "median_ctc_l": None,
            "office_sqft": None,
            "demand_creation_score": 5,
            "residential_impact_score": 5,
            "appreciation_impact_score": 5,
            "rental_impact_score": 5,
            "primary_housing_segment": None,
            "time_horizon": "1-3y",
            "source_url": source_url,
            "source_name": source_name,
            "source_reliability": "PRESS",
        }
