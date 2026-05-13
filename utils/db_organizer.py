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

        logger.info(f"[DBOrganizer] Starting upsert for {market_name} — {len(records)} records")

        for project in records:
            try:
                with self.engine.begin() as conn:
                    dev_id    = self._upsert_developer(conn, project)
                    market_id = self._get_market_id(conn, project)
                    self._update_developer_grade(conn, dev_id, project)
                    action    = self._upsert_project(conn, project, dev_id, market_id)
                    if action == "inserted":
                        inserted += 1
                    else:
                        updated += 1
            except Exception as exc:
                logger.error(
                    f"[DBOrganizer] Upsert failed for "
                    f"'{project.get('rera_number', '?')}': {exc}"
                )
                failed += 1

        duration = int(time.time() - started)
        stats = {
            "market":   market_name,
            "total":    len(records),
            "inserted": inserted,
            "updated":  updated,
            "failed":   failed,
            "duration_seconds": duration,
        }

        self._log_run(market_name, stats)
        logger.info(
            f"[DBOrganizer] Done — {inserted} inserted, {updated} updated, "
            f"{failed} failed ({duration}s)"
        )
        return stats

    # ── Developer ──────────────────────────────────────────────────────────────

    def _upsert_developer(self, conn, project: dict) -> str | None:
        dev_name = str(project.get("developer_name", "Unknown Developer")).strip()
        dev_norm = dev_name.lower()

        row = conn.execute(text("""
            INSERT INTO developers (name, name_normalized)
            VALUES (:name, :norm)
            ON CONFLICT (name_normalized) DO NOTHING
            RETURNING id
        """), {"name": dev_name, "norm": dev_norm}).fetchone()

        if row:
            return str(row[0])

        row = conn.execute(
            text("SELECT id FROM developers WHERE name_normalized = :n"),
            {"n": dev_norm},
        ).fetchone()
        return str(row[0]) if row else None

    def _update_developer_grade(self, conn, developer_id: str | None, project: dict):
        if not developer_id:
            return
        dev_lower  = str(project.get("developer_name", "")).lower()
        total_units = project.get("total_units", 0)

        grade = "C"
        for known in GRADE_A_DEVELOPERS:
            if known in dev_lower:
                grade = "A"
                break
        if grade == "C":
            if total_units >= GRADE_A_MIN_UNITS:
                grade = "A"
            elif total_units >= GRADE_B_MIN_UNITS:
                grade = "B"

        conn.execute(
            text("UPDATE developers SET grade = :g WHERE id = :id"),
            {"g": grade, "id": developer_id},
        )

    # ── Micro-market ───────────────────────────────────────────────────────────

    def _get_market_id(self, conn, project: dict) -> str | None:
        locality = str(project.get("locality", "")).lower()
        taluk    = str(project.get("taluk", "")).lower()

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
            "rera_number":    project.get("rera_number", ""),
            "project_name":   project.get("project_name", ""),
            "developer_id":   dev_id,
            "market_id":      market_id,
            "address":        project.get("address"),
            "district":       project.get("district"),
            "taluk":          project.get("taluk"),
            "locality":       project.get("locality"),
            "project_type":   project.get("project_type", "Residential"),
            "project_status": project.get("project_status"),
            "total_units":    int(project.get("total_units", 0) or 0),
            "sold_units":     int(project.get("sold_units", 0) or 0),
            "unsold_units":   int(project.get("unsold_units", 0) or 0),
            "possession_date":   _safe_date(project.get("possession_date")),
            "registration_date": _safe_date(project.get("registration_date")),
            "raw_data":       raw_data_json,
        }

        conn.execute(text("""
            INSERT INTO rera_projects (
                rera_number, project_name, developer_id, micro_market_id,
                address, district, taluk, locality,
                project_type, project_status,
                total_units, sold_units, unsold_units,
                possession_date, registration_date,
                raw_data, last_scraped_at
            ) VALUES (
                :rera_number, :project_name, :developer_id, :market_id,
                :address, :district, :taluk, :locality,
                :project_type, :project_status,
                :total_units, :sold_units, :unsold_units,
                :possession_date, :registration_date,
                CAST(:raw_data AS jsonb), NOW()
            )
            ON CONFLICT (rera_number) DO UPDATE SET
                project_name    = EXCLUDED.project_name,
                developer_id    = COALESCE(EXCLUDED.developer_id, rera_projects.developer_id),
                micro_market_id = COALESCE(EXCLUDED.micro_market_id, rera_projects.micro_market_id),
                project_status  = EXCLUDED.project_status,
                total_units     = EXCLUDED.total_units,
                sold_units      = EXCLUDED.sold_units,
                unsold_units    = EXCLUDED.unsold_units,
                possession_date = EXCLUDED.possession_date,
                raw_data        = EXCLUDED.raw_data,
                last_scraped_at = NOW(),
                updated_at      = NOW()
        """), params)

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

        # Guidance values
        for rec in gv_records:
            try:
                with self.engine.begin() as conn:
                    market_id = self._get_market_id_by_name(conn, market_name)
                    action = self._upsert_guidance_value(conn, rec, market_id)
                    if action == "inserted":
                        gv_inserted += 1
                    else:
                        gv_updated += 1
            except Exception as exc:
                logger.error(f"[DBOrganizer] GV upsert failed: {exc}")

        # Registrations
        for rec in reg_records:
            try:
                with self.engine.begin() as conn:
                    market_id = self._get_market_id_by_name(conn, market_name)
                    self._insert_registration(conn, rec, market_id)
                    reg_inserted += 1
            except Exception as exc:
                err = str(exc)
                # duplicate key = already recorded, not a real failure
                if "unique" in err.lower() or "duplicate" in err.lower():
                    pass
                else:
                    logger.error(f"[DBOrganizer] Registration insert failed: {exc}")
                    reg_failed += 1

        duration = int(_time.time() - started)
        stats = {
            "market":       market_name,
            "gv_inserted":  gv_inserted,
            "gv_updated":   gv_updated,
            "reg_inserted": reg_inserted,
            "reg_failed":   reg_failed,
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
        """Upsert one guidance value record. Returns 'inserted' or 'updated'."""
        existing = conn.execute(text("""
            SELECT id FROM guidance_values
            WHERE micro_market_id = :mid
              AND locality = :locality
              AND property_type = :ptype
              AND effective_from = :eff
        """), {
            "mid":      market_id,
            "locality": rec.get("locality", ""),
            "ptype":    rec.get("property_type", "Residential"),
            "eff":      _safe_date(rec.get("effective_from")) or "2024-04-01",
        }).fetchone()

        params = {
            "mid":      market_id,
            "locality": rec.get("locality", ""),
            "ptype":    rec.get("property_type", "Residential"),
            "road":     rec.get("road_type", "Main Road"),
            "psf":      float(rec.get("guidance_value_psf", 0) or 0),
            "sqm":      round(float(rec.get("guidance_value_psf", 0) or 0) * 10.764, 2),
            "eff":      _safe_date(rec.get("effective_from")) or "2024-04-01",
        }

        if existing:
            conn.execute(text("""
                UPDATE guidance_values SET
                    guidance_value_psf    = :psf,
                    guidance_value_per_sqm = :sqm,
                    road_type             = :road
                WHERE micro_market_id = :mid
                  AND locality = :locality
                  AND property_type = :ptype
                  AND effective_from = :eff
            """), params)
            return "updated"
        else:
            conn.execute(text("""
                INSERT INTO guidance_values (
                    micro_market_id, locality, property_type, road_type,
                    guidance_value_psf, guidance_value_per_sqm, effective_from
                ) VALUES (
                    :mid, :locality, :ptype, :road,
                    :psf, :sqm, :eff
                )
            """), params)
            return "inserted"

    # ── Kaveri — registrations ─────────────────────────────────────────────────

    def _insert_registration(self, conn, rec: dict, market_id: str | None):
        """Insert one Kaveri registration. Skips on duplicate registration_number."""
        raw_json = json.dumps(rec.get("raw_data", {}), default=str)
        params = {
            "reg_no":    rec.get("registration_number", ""),
            "doc_no":    rec.get("document_number", ""),
            "mid":       market_id,
            "ptype":     rec.get("property_type", "Apartment"),
            "pdesc":     rec.get("property_description", ""),
            "area_sqft": float(rec.get("area_sqft", 0) or 0),
            "area_sqm":  round(float(rec.get("area_sqft", 0) or 0) * 0.0929, 2),
            "amt":       float(rec.get("transaction_amount", 0) or 0),
            "gv":        float(rec.get("guidance_value", 0) or 0),
            "stamp":     float(rec.get("stamp_duty_paid", 0) or 0),
            "reg_fee":   float(rec.get("registration_fee", 0) or 0),
            "buyer":     rec.get("buyer_name", ""),
            "seller":    rec.get("seller_name", ""),
            "survey":    rec.get("survey_number", ""),
            "village":   rec.get("village", ""),
            "hobli":     rec.get("hobli", ""),
            "taluk":     rec.get("taluk", ""),
            "district":  rec.get("district", ""),
            "txn_date":  _safe_date(rec.get("transaction_date")),
            "reg_date":  _safe_date(rec.get("registration_date")),
            "raw":       raw_json,
        }
        conn.execute(text("""
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
                raw_data
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
                CAST(:raw AS jsonb)
            )
            ON CONFLICT DO NOTHING
        """), params)

    # ── Run logging ────────────────────────────────────────────────────────────

    def _log_run(self, market_name: str, stats: dict):
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO agent_runs (
                        agent_name, task_type, micro_market, status,
                        records_inserted, records_updated, records_failed,
                        completed_at
                    ) VALUES (
                        'organizer', 'rera_ingest', :market, 'completed',
                        :inserted, :updated, :failed,
                        NOW()
                    )
                """), {
                    "market":   market_name,
                    "inserted": stats.get("inserted", 0),
                    "updated":  stats.get("updated", 0),
                    "failed":   stats.get("failed", 0),
                })
        except Exception as exc:
            logger.warning(f"[DBOrganizer] Failed to log run to DB: {exc}")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_date(val):
    """Return val if it looks like a date string, else None."""
    if not val:
        return None
    s = str(val).strip()
    if len(s) >= 10 and s[4] == "-":   # YYYY-MM-DD prefix check
        return s[:10]
    return None
