"""
RE_OS — Pure Python DB Organizer
──────────────────────────────────
Replaces the CrewAI Organizer agent for database writes.
No LLM. No hallucination risk. No per-record round-trips.

What it does:
  1. Batch upserts validated RERA project records
  2. Upserts developers, links to micro-markets
  3. Updates developer grades
  4. Logs the run to agent_runs table

Why pure Python:
  DB writes are deterministic. Using an LLM to call upsert 8× per project
  wastes ~500 tokens per run, risks hallucinating tool calls, and is 100× slower.

Usage:
    from utils.db_organizer import DBOrganizer
    org = DBOrganizer()
    stats = org.run("Yelahanka", validated_records)
    # stats = {"market": "Yelahanka", "total": 8, "inserted": 6, "updated": 2, "failed": 0}
"""

import json
import time
from datetime import datetime
from loguru import logger
from sqlalchemy import create_engine, text
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import (
    DATABASE_URL,
    GRADE_A_DEVELOPERS,
    GRADE_A_MIN_UNITS,
    GRADE_B_MIN_UNITS,
    MARKET_RERA_KEYWORDS,
)


class DBOrganizer:
    """
    Handles all DB writes for one market run.
    Thread-safe per instance (each call to run() creates its own engine connection).
    """

    def __init__(self):
        self.engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    # ── Public ─────────────────────────────────────────────────────────────────

    def run(self, market_name: str, records: list) -> dict:
        """
        Batch upsert validated RERA records for a market.
        Returns stats dict — also logs run to agent_runs table.
        """
        started = time.time()
        inserted = updated = failed = 0
        dev_grade_inputs: dict[str, tuple[str, int]] = {}  # dev_id → (name, max_units)

        logger.info(
            f"[DBOrganizer] Starting upsert for {market_name} — {len(records)} records"
        )

        with self.engine.begin() as conn:
            for i, project in enumerate(records):
                sp = f"sp_rera_{i}"
                try:
                    conn.execute(text(f"SAVEPOINT {sp}"))
                    dev_id = self._upsert_developer(conn, project)
                    market_id = self._get_market_id(conn, project)
                    action = self._upsert_project(conn, project, dev_id, market_id)
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    if dev_id:
                        dev_name = str(project.get("developer_name", "")).strip()
                        units = int(project.get("total_units", 0) or 0)
                        if dev_id not in dev_grade_inputs or units > dev_grade_inputs[dev_id][1]:
                            dev_grade_inputs[dev_id] = (dev_name, units)
                    if action == "inserted":
                        inserted += 1
                    else:
                        updated += 1
                except Exception as exc:
                    conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    logger.error(
                        f"[DBOrganizer] Upsert failed for "
                        f"'{project.get('rera_number', '?')}': {exc}"
                    )
                    failed += 1

            # Single batch UPDATE for all developer grades — replaces N per-record calls.
            # Non-fatal: grade data is derived; project upserts are the critical path.
            try:
                self._batch_update_developer_grades(conn, dev_grade_inputs)
            except Exception as grade_exc:
                logger.warning(
                    f"[DBOrganizer] Developer grade batch UPDATE failed (non-fatal): {grade_exc}"
                )

        duration = int(time.time() - started)
        stats = {
            "market": market_name,
            "total": len(records),
            "inserted": inserted,
            "updated": updated,
            "failed": failed,
            "duration_seconds": duration,
        }

        self._log_run(market_name, stats)
        logger.info(
            f"[DBOrganizer] Done — {inserted} inserted, {updated} updated, "
            f"{failed} failed ({duration}s)"
        )
        return stats

    def run_portal_scout(self, market_name: str, findings: list) -> dict:
        """Upsert portal scout findings into listings table using cid."""
        started = time.time()
        upserted = failed = 0
        table = "listings"

        with self.engine.begin() as conn:
            for i, rec in enumerate(findings):
                sp = f"sp_portal_{i}"
                try:
                    conn.execute(text(f"SAVEPOINT {sp}"))
                    market_id = self._get_market_id_by_name(conn, market_name)
                    self._upsert_listing_by_cid(conn, rec, market_id)
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    upserted += 1
                except Exception as exc:
                    conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    logger.error(f"[Organizer] portal upsert failed: {exc}")
                    failed += 1

        duration = int(time.time() - started)
        logger.info(
            f"[Organizer] {market_name}: {upserted} records upserted into {table}"
        )
        return {
            "market": market_name,
            "total": len(findings),
            "upserted": upserted,
            "failed": failed,
            "duration_seconds": duration,
        }

    def run_developer_scout(self, market_name: str, findings: list) -> dict:
        """Upsert developer scout findings into listings table using cid."""
        started = time.time()
        upserted = failed = 0
        table = "listings"

        with self.engine.begin() as conn:
            for i, rec in enumerate(findings):
                sp = f"sp_dev_{i}"
                try:
                    conn.execute(text(f"SAVEPOINT {sp}"))
                    market_id = self._get_market_id_by_name(conn, market_name)
                    source_val = (
                        str(rec.get("source", "developer")).strip() or "developer"
                    )
                    if not source_val.startswith("dev_"):
                        rec = dict(rec)
                        rec["source"] = f"dev_{source_val}"
                    self._upsert_listing_by_cid(conn, rec, market_id)
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    upserted += 1
                except Exception as exc:
                    conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    logger.error(f"[Organizer] developer upsert failed: {exc}")
                    failed += 1

        duration = int(time.time() - started)
        logger.info(
            f"[Organizer] {market_name}: {upserted} records upserted into {table}"
        )
        return {
            "market": market_name,
            "total": len(findings),
            "upserted": upserted,
            "failed": failed,
            "duration_seconds": duration,
        }

    def run_news_scout(self, market_name: str, findings: list) -> dict:
        """Insert news findings into news_articles; skip safely if table missing."""
        started = time.time()
        inserted = failed = 0
        table = "news_articles"

        with self.engine.begin() as conn:
            exists = conn.execute(
                text("SELECT to_regclass('public.news_articles')")
            ).scalar()

        if not exists:
            logger.warning(
                "[Organizer] news_articles table missing. Skipping run_news_scout without failing pipeline."
            )
            return {
                "market": market_name,
                "total": len(findings),
                "inserted": 0,
                "failed": 0,
                "duration_seconds": int(time.time() - started),
            }

        with self.engine.begin() as conn:
            for i, rec in enumerate(findings):
                sp = f"sp_news_{i}"
                try:
                    conn.execute(text(f"SAVEPOINT {sp}"))
                    self._insert_news_article(conn, rec)
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    inserted += 1
                except Exception as exc:
                    conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    logger.error(f"[Organizer] news insert failed: {exc}")
                    failed += 1

        duration = int(time.time() - started)
        logger.info(
            f"[Organizer] {market_name}: {inserted} records upserted into {table}"
        )
        return {
            "market": market_name,
            "total": len(findings),
            "inserted": inserted,
            "failed": failed,
            "duration_seconds": duration,
        }

    def run_rera_detail_scout(self, market_name: str, findings: list) -> dict:
        """Upsert RERA detail enriched data into rera_projects (Stage 2 upsert).

        Maps enriched fields (unit_mix, project_cost_crore, amenities, approvals, etc.)
        to typed rera_projects columns. Creates record if rera_number not yet in DB.

        Returns stats dict: {inserted, updated, skipped, failed, duration_seconds}.
        """
        started = time.time()
        inserted = updated = skipped = failed = 0

        logger.info(
            f"[DBOrganizer] RERA detail upsert for {market_name} — {len(findings)} records"
        )

        with self.engine.begin() as conn:
            for i, rec in enumerate(findings):
                rera_num = str(rec.get("rera_number", "")).strip()
                if not rera_num:
                    skipped += 1
                    continue
                sp = f"sp_detail_{i}"
                try:
                    conn.execute(text(f"SAVEPOINT {sp}"))
                    action = self._upsert_rera_detail(conn, rec)
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    if action == "inserted":
                        inserted += 1
                    elif action == "updated":
                        updated += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    logger.error(
                        f"[DBOrganizer] rera_detail upsert failed for {rera_num}: {exc}"
                    )
                    failed += 1

        duration = int(time.time() - started)
        logger.info(
            f"[DBOrganizer] RERA detail done — {inserted} inserted, {updated} updated, "
            f"{skipped} no-match, {failed} failed ({duration}s)"
        )
        return {
            "market": market_name,
            "total": len(findings),
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "duration_seconds": duration,
        }

    # ── Developer ──────────────────────────────────────────────────────────────

    def _upsert_developer(self, conn, project: dict) -> str | None:
        dev_name = str(project.get("developer_name", "Unknown Developer")).strip()
        dev_norm = dev_name.lower()

        row = conn.execute(
            text("""
            INSERT INTO developers (name, name_normalized)
            VALUES (:name, :norm)
            ON CONFLICT (name_normalized) DO NOTHING
            RETURNING id
        """),
            {"name": dev_name, "norm": dev_norm},
        ).fetchone()

        if row:
            return str(row[0])

        row = conn.execute(
            text("SELECT id FROM developers WHERE name_normalized = :n"),
            {"n": dev_norm},
        ).fetchone()
        return str(row[0]) if row else None

    @staticmethod
    def _compute_grade(dev_name: str, total_units: int) -> str:
        dev_lower = dev_name.lower()
        for known in GRADE_A_DEVELOPERS:
            if known in dev_lower:
                return "A"
        if total_units >= GRADE_A_MIN_UNITS:
            return "A"
        if total_units >= GRADE_B_MIN_UNITS:
            return "B"
        return "C"

    def _batch_update_developer_grades(
        self, conn, grade_inputs: dict[str, tuple[str, int]]
    ) -> None:
        """Single executemany UPDATE for all developers touched in this run.

        Replaces N individual UPDATE calls with one batched statement.
        Grades are computed from the max total_units seen per developer,
        so a developer with projects of varying sizes is graded correctly.
        """
        if not grade_inputs:
            return
        params = [
            {"grade": self._compute_grade(name, units), "id": dev_id}
            for dev_id, (name, units) in grade_inputs.items()
        ]
        conn.execute(text("UPDATE developers SET grade = :grade WHERE id = :id"), params)
        logger.debug(f"[DBOrganizer] Batch graded {len(params)} developers")

    # ── Micro-market ───────────────────────────────────────────────────────────

    def _get_market_id(self, conn, project: dict) -> str | None:
        locality = str(project.get("locality", "")).lower()
        taluk = str(project.get("taluk", "")).lower()

        for market_name, keywords in MARKET_RERA_KEYWORDS.items():
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in locality or kw_lower in taluk:
                    row = conn.execute(
                        text("SELECT id FROM micro_markets WHERE name = :n"),
                        {"n": market_name},
                    ).fetchone()
                    if row:
                        return str(row[0])
        return None

    # ── RERA project ───────────────────────────────────────────────────────────

    def _upsert_project(
        self, conn, project: dict, dev_id: str | None, market_id: str | None
    ) -> str:
        """Returns 'inserted' or 'updated'."""

        # Check if already exists
        existing = conn.execute(
            text("SELECT id FROM rera_projects WHERE rera_number = :rn"),
            {"rn": project.get("rera_number", "")},
        ).fetchone()

        raw_data_json = json.dumps(project.get("raw_data", {}), default=str)

        params = {
            "rera_number": project.get("rera_number", ""),
            "project_name": project.get("project_name", ""),
            "developer_id": dev_id,
            "market_id": market_id,
            "address": project.get("address"),
            "district": project.get("district"),
            "taluk": project.get("taluk"),
            "locality": project.get("locality"),
            "project_type": project.get("project_type", "Residential"),
            "project_status": project.get("project_status"),
            "total_units": int(project.get("total_units", 0) or 0),
            "sold_units": int(project.get("sold_units", 0) or 0),
            "unsold_units": int(project.get("unsold_units", 0) or 0),
            "possession_date": _safe_date(project.get("possession_date")),
            "registration_date": _safe_date(project.get("registration_date")),
            "raw_data": raw_data_json,
        }

        conn.execute(
            text("""
            INSERT INTO rera_projects (
                rera_number, project_name, developer_id, micro_market_id,
                address, district, taluk, locality,
                project_type, project_status,
                total_units, sold_units, unsold_units,
                possession_date, registration_date,
                raw_data, last_scraped_at, data_source
            ) VALUES (
                :rera_number, :project_name, :developer_id, :market_id,
                :address, :district, :taluk, :locality,
                :project_type, :project_status,
                :total_units, :sold_units, :unsold_units,
                :possession_date, :registration_date,
                CAST(:raw_data AS jsonb), NOW(), 'portal_scraped'
            )
            ON CONFLICT (rera_number) DO UPDATE SET
                project_name    = EXCLUDED.project_name,
                developer_id    = COALESCE(EXCLUDED.developer_id, rera_projects.developer_id),
                micro_market_id = EXCLUDED.micro_market_id,
                project_status  = EXCLUDED.project_status,
                total_units     = EXCLUDED.total_units,
                sold_units      = EXCLUDED.sold_units,
                unsold_units    = EXCLUDED.unsold_units,
                possession_date = EXCLUDED.possession_date,
                raw_data        = EXCLUDED.raw_data,
                last_scraped_at = NOW(),
                data_source     = 'portal_scraped',
                updated_at      = NOW()
        """),
            params,
        )

        return "updated" if existing else "inserted"

    # ── Kaveri — public entry point ────────────────────────────────────────────

    def run_kaveri(self, market_name: str, gv_records: list, reg_records: list) -> dict:
        """
        Batch upsert Kaveri guidance values + registrations for a market.
        Returns stats dict: {gv_inserted, gv_updated, reg_inserted, reg_failed}.
        """
        import time as _time

        started = _time.time()
        gv_inserted = gv_updated = reg_inserted = reg_failed = 0

        logger.info(
            f"[DBOrganizer] Kaveri upsert for {market_name} — "
            f"{len(gv_records)} GV records, {len(reg_records)} registrations"
        )

        with self.engine.begin() as conn:
            # Guidance values
            for i, rec in enumerate(gv_records):
                sp = f"sp_gv_{i}"
                try:
                    conn.execute(text(f"SAVEPOINT {sp}"))
                    market_id = self._get_market_id_by_name(conn, market_name)
                    action = self._upsert_guidance_value(conn, rec, market_id)
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    if action == "inserted":
                        gv_inserted += 1
                    else:
                        gv_updated += 1
                except Exception as exc:
                    conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    logger.error(f"[DBOrganizer] GV upsert failed: {exc}")

            # Registrations
            for i, rec in enumerate(reg_records):
                sp = f"sp_reg_{i}"
                try:
                    conn.execute(text(f"SAVEPOINT {sp}"))
                    market_id = self._get_market_id_by_name(conn, market_name)
                    self._insert_registration(conn, rec, market_id)
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    reg_inserted += 1
                except Exception as exc:
                    conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    err = str(exc)
                    # duplicate key = already recorded, not a real failure
                    if "unique" in err.lower() or "duplicate" in err.lower():
                        pass
                    else:
                        logger.error(f"[DBOrganizer] Registration insert failed: {exc}")
                        reg_failed += 1

        duration = int(_time.time() - started)
        stats = {
            "market": market_name,
            "gv_inserted": gv_inserted,
            "gv_updated": gv_updated,
            "reg_inserted": reg_inserted,
            "reg_failed": reg_failed,
            "duration_seconds": duration,
        }
        logger.info(
            f"[DBOrganizer] Kaveri done — GV {gv_inserted}+{gv_updated}, "
            f"Reg {reg_inserted} inserted, {reg_failed} failed ({duration}s)"
        )
        return stats

    # ── Kaveri — guidance values ───────────────────────────────────────────────

    def _get_market_id_by_name(self, conn, market_name: str) -> str | None:
        """Look up micro_market.id directly by name (no keyword matching needed)."""
        row = conn.execute(
            text("SELECT id FROM micro_markets WHERE name ILIKE :n LIMIT 1"),
            {"n": f"%{market_name}%"},
        ).fetchone()
        return str(row[0]) if row else None

    def _upsert_guidance_value(self, conn, rec: dict, market_id: str | None) -> str:
        """Upsert one guidance value record. Returns 'inserted' or 'updated'.

        Uses ON CONFLICT against idx_guidance_values_unique to avoid race conditions
        from the old SELECT-then-INSERT pattern.
        """
        eff_date = _safe_date(rec.get("effective_from")) or "2024-04-01"
        params = {
            "mid": market_id,
            "locality": rec.get("locality", ""),
            "ptype": rec.get("property_type", "Residential"),
            "road": rec.get("road_type", "Main Road"),
            "psf": float(rec.get("guidance_value_psf", 0) or 0),
            "sqm": round(float(rec.get("guidance_value_psf", 0) or 0) * 10.764, 2),
            "eff": eff_date,
        }

        result = conn.execute(
            text("""
            INSERT INTO guidance_values (
                micro_market_id, locality, property_type, road_type,
                guidance_value_psf, guidance_value_per_sqm, effective_from,
                data_source
            ) VALUES (
                :mid, :locality, :ptype, :road,
                :psf, :sqm, :eff,
                'portal_scraped'
            )
            ON CONFLICT (micro_market_id, locality, property_type, effective_from)
            WHERE micro_market_id IS NOT NULL
            DO UPDATE SET
                guidance_value_psf     = EXCLUDED.guidance_value_psf,
                guidance_value_per_sqm = EXCLUDED.guidance_value_per_sqm,
                road_type              = EXCLUDED.road_type
            RETURNING (xmax = 0) AS inserted
        """),
            params,
        ).fetchone()

        return "inserted" if (result and result[0]) else "updated"

    # ── Kaveri — registrations ─────────────────────────────────────────────────

    def _insert_registration(self, conn, rec: dict, market_id: str | None):
        """Insert one Kaveri registration. Skips on duplicate registration_number."""
        raw_json = json.dumps(rec.get("raw_data", {}), default=str)
        params = {
            "reg_no": rec.get("registration_number", ""),
            "doc_no": rec.get("document_number", ""),
            "mid": market_id,
            "ptype": rec.get("property_type", "Apartment"),
            "pdesc": rec.get("property_description", ""),
            "area_sqft": float(rec.get("area_sqft", 0) or 0),
            "area_sqm": round(float(rec.get("area_sqft", 0) or 0) * 0.0929, 2),
            "amt": float(rec.get("transaction_amount", 0) or 0),
            "gv": float(rec.get("guidance_value", 0) or 0),
            "stamp": float(rec.get("stamp_duty_paid", 0) or 0),
            "reg_fee": float(rec.get("registration_fee", 0) or 0),
            "buyer": rec.get("buyer_name", ""),
            "seller": rec.get("seller_name", ""),
            "survey": rec.get("survey_number", ""),
            "village": rec.get("village", ""),
            "hobli": rec.get("hobli", ""),
            "taluk": rec.get("taluk", ""),
            "district": rec.get("district", ""),
            "txn_date": _safe_date(rec.get("transaction_date")),
            "reg_date": _safe_date(rec.get("registration_date")),
            "raw": raw_json,
        }
        conn.execute(
            text("""
            INSERT INTO kaveri_registrations (
                registration_number, document_number,
                micro_market_id,
                property_type, property_description,
                area_sqft, area_sqm,
                transaction_amount, guidance_value,
                stamp_duty_paid, registration_fee,
                buyer_name, seller_name,
                survey_number, village, hobli, taluk, district,
                transaction_date, registration_date,
                raw_data, data_source
            ) VALUES (
                :reg_no, :doc_no,
                :mid,
                :ptype, :pdesc,
                :area_sqft, :area_sqm,
                :amt, :gv,
                :stamp, :reg_fee,
                :buyer, :seller,
                :survey, :village, :hobli, :taluk, :district,
                :txn_date, :reg_date,
                CAST(:raw AS jsonb), 'portal_scraped'
            )
            ON CONFLICT (registration_number)
            WHERE registration_number IS NOT NULL AND registration_number != ''
            DO NOTHING
        """),
            params,
        )

    def _upsert_listing_by_cid(self, conn, rec: dict, market_id: str | None):
        cid = str(rec.get("cid", "")).strip()
        if not cid:
            raise ValueError("listing record missing cid")

        source = str(rec.get("source", "unknown")).strip() or "unknown"
        project_name = rec.get("project_name")
        locality = rec.get("locality")
        scraped_at = _safe_date(rec.get("scraped_at")) or datetime.utcnow().strftime(
            "%Y-%m-%d"
        )
        listed_price = float(rec.get("price_min", 0) or 0)

        conn.execute(
            text("""
            INSERT INTO listings (
                source, source_listing_id, micro_market_id,
                address, locality, listed_price,
                listed_at, first_seen_at, last_seen_at,
                raw_data, data_source
            ) VALUES (
                :source, :cid, :market_id,
                :project_name, :locality, :listed_price,
                :listed_at, NOW(), NOW(),
                CAST(:raw_data AS jsonb), 'portal_scraped'
            )
            ON CONFLICT (source, source_listing_id) DO UPDATE SET
                micro_market_id = EXCLUDED.micro_market_id,
                address = EXCLUDED.address,
                locality = EXCLUDED.locality,
                listed_price = EXCLUDED.listed_price,
                listed_at = EXCLUDED.listed_at,
                last_seen_at = NOW(),
                raw_data = EXCLUDED.raw_data,
                updated_at = NOW()
        """),
            {
                "source": source,
                "cid": cid,
                "market_id": market_id,
                "project_name": project_name,
                "locality": locality,
                "listed_price": listed_price,
                "listed_at": scraped_at,
                "raw_data": json.dumps(rec, default=str),
            },
        )

    def _insert_news_article(self, conn, rec: dict):
        params = {
            "cid": rec.get("cid", ""),
            "title": rec.get("title", ""),
            "source": rec.get("source", "unknown"),
            "url": rec.get("url", ""),
            "published_at": _safe_date(rec.get("published_at") or rec.get("date")),
            "summary": rec.get("summary", ""),
            "raw_data": json.dumps(rec, default=str),
        }
        conn.execute(
            text("""
            INSERT INTO news_articles (cid, title, source, source_url, published_at, summary, raw_data)
            VALUES (:cid, :title, :source, :url, :published_at, :summary, CAST(:raw_data AS jsonb))
            ON CONFLICT (cid) DO NOTHING
        """),
            params,
        )

    def _upsert_rera_detail(self, conn, rec: dict) -> str:
        """Enrich an existing rera_projects row from RERA detail-page data.

        rera_detail_scout runs AFTER the regular RERA listing scrape + organizer,
        so the target row always exists. This is a pure UPDATE — no INSERT path.
        Approval numbers (BDA, BBMP) are stored in raw_data JSONB; they are NOT
        mapped to architect_name / ca_name, which are reserved for persons.

        Returns 'updated' or 'skipped' (no matching rera_number in DB).
        """
        rera_num = str(rec.get("rera_number", "")).strip()

        # Build area conversions
        site_area_sqft = float(rec.get("site_area_sqft", 0) or 0)
        total_land_sqm = round(site_area_sqft * 0.0929, 2) if site_area_sqft else None

        fsi_utilized = float(rec.get("fsi_utilized", 0) or 0)
        total_built_sqm = None
        if fsi_utilized and total_land_sqm:
            total_built_sqm = round(fsi_utilized * total_land_sqm, 2)

        project_cost = float(rec.get("project_cost_crore", 0) or 0)
        cost_rupees = round(project_cost * 10_000_000, 2) if project_cost else None

        total_units = int(rec.get("total_units", 0) or 0) or None
        no_of_floors = int(rec.get("no_of_floors", 0) or 0) or None
        completion_pct = float(rec.get("completion_pct", 0) or 0) or None

        unit_mix = rec.get("unit_mix")
        if unit_mix is not None:
            unit_mix = json.dumps(unit_mix, default=str)

        amenities = rec.get("amenities")
        if amenities is not None:
            amenities = json.dumps(amenities, default=str)

        bda_no = rec.get("bda_approval_no")
        bbmp_no = rec.get("bbmp_approval_no")

        poss_date = _safe_date(rec.get("possession_date"))
        plan_date = _safe_date(rec.get("plan_approval_date"))
        project_addr = rec.get("project_address")

        # Check record exists before building the UPDATE
        existing = conn.execute(
            text("SELECT id FROM rera_projects WHERE rera_number = :rn"),
            {"rn": rera_num},
        ).fetchone()

        if not existing:
            return "skipped"

        # Build UPDATE dynamically — only set fields that are present in this record
        params: dict = {"rn": rera_num}
        set_clauses = ["last_scraped_at = NOW()"]

        if total_units is not None:
            params["total_units"] = total_units
            set_clauses.append("total_units = :total_units")
        if total_land_sqm is not None:
            params["total_land_area_sqm"] = total_land_sqm
            set_clauses.append("total_land_area_sqm = :total_land_area_sqm")
        if total_built_sqm is not None:
            params["total_built_up_area_sqm"] = total_built_sqm
            set_clauses.append("total_built_up_area_sqm = :total_built_up_area_sqm")
        if cost_rupees is not None:
            params["estimated_project_cost"] = cost_rupees
            set_clauses.append("estimated_project_cost = :estimated_project_cost")
        if unit_mix is not None:
            params["unit_mix"] = unit_mix
            set_clauses.append("unit_mix = CAST(:unit_mix AS jsonb)")
        if amenities is not None:
            params["amenities"] = amenities
            set_clauses.append("amenities = CAST(:amenities AS jsonb)")
        if completion_pct is not None:
            params["completion_pct"] = completion_pct
            set_clauses.append("completion_pct = :completion_pct")
        if poss_date:
            params["possession_date"] = poss_date
            set_clauses.append("possession_date = :possession_date")
        if plan_date:
            params["plan_approval_date"] = plan_date
            set_clauses.append("plan_approval_date = :plan_approval_date")
        if project_addr:
            params["project_address"] = project_addr
            set_clauses.append("address = COALESCE(NULLIF(address, ''), :project_address)")

        # Approval numbers + extra fields → raw_data JSONB only (not typed columns)
        raw_enrich = {
            k: v
            for k, v in {
                "unit_mix": rec.get("unit_mix"),
                "project_cost_crore": rec.get("project_cost_crore"),
                "completion_pct": rec.get("completion_pct"),
                "amenities": rec.get("amenities"),
                "bda_approval_no": bda_no,
                "bbmp_approval_no": bbmp_no,
                "no_of_floors": no_of_floors,
                "plan_approval_date": plan_date,
            }.items()
            if v is not None
        }
        if raw_enrich:
            params["raw_extra"] = json.dumps(raw_enrich, default=str)
            set_clauses.append(
                "raw_data = COALESCE(raw_data, '{}'::jsonb) || CAST(:raw_extra AS jsonb)"
            )

        set_clause = ", ".join(set_clauses)
        conn.execute(
            text(f"UPDATE rera_projects SET {set_clause} WHERE rera_number = :rn"),
            params,
        )
        return "updated"

    # ── Run logging ────────────────────────────────────────────────────────────

    def _log_run(self, market_name: str, stats: dict):
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("""
                    INSERT INTO agent_runs (
                        agent_name, task_type, micro_market, status,
                        records_inserted, records_updated, records_failed,
                        duration_seconds, completed_at
                    ) VALUES (
                        'organizer', 'rera_ingest', :market, 'completed',
                        :inserted, :updated, :failed,
                        :duration, NOW()
                    )
                """),
                    {
                        "market": market_name,
                        "inserted": stats.get("inserted", 0),
                        "updated": stats.get("updated", 0),
                        "failed": stats.get("failed", 0),
                        "duration": stats.get("duration_seconds", 0),
                    },
                )
        except Exception as exc:
            logger.warning(f"[DBOrganizer] Failed to log run to DB: {exc}")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _safe_date(val):
    """Return val if it looks like a date string, else None."""
    if not val:
        return None
    s = str(val).strip()
    if len(s) >= 10 and s[4] == "-":  # YYYY-MM-DD prefix check
        return s[:10]
    return None
