"""
RE_OS — Ingest Writer (Sprint 61 — Unified Ingest Engine)

Routes :class:`~ingest.base.ParsedRecord` instances to the correct DB table
based on ``entity_type``.  Uses PostgreSQL SAVEPOINTs for per-row isolation
within a batch transaction and ``ON CONFLICT … DO UPDATE`` for idempotent
upserts wherever a natural-key unique constraint exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger
from sqlalchemy import text

from utils.db import get_engine
from ingest.base import ParsedRecord

__all__ = [
    "IngestWriter", "WriteResult", "route_record",
]


# ── Entity-type → DB table mapping ─────────────────────────────────────────────

_ENTITY_TABLE_MAP: dict[str, str] = {
    "rera_project": "rera_projects",
    "listing": "listings",
    "kaveri_registration": "kaveri_registrations",
    "igr_transaction": "igr_transactions",
    "guidance_value": "guidance_values",
    "news_article": "news_articles",
    "survey": "surveys",
    "rtc_record": "rtc_records",
    "khata_record": "khata_records",
    "litigation": "litigations",
    "distressed_opp": "distressed_opps",
    "developer_health": "developer_health",
    "demand_signal": "demand_signals",
    "deal": "deals",
    "opportunity_score": "opportunity_scores",
    "registered_transaction": "registered_transactions",
}

# ── Conflict-column resolution ─────────────────────────────────────────────────
# Each entry maps a table name to the conflict-target column(s) used for
# ON CONFLICT (col) DO UPDATE.  A None entry means plain INSERT (no upsert).
# Composite keys use a two-element tuple; the writer generates the correct
# ON CONFLICT (col1, col2) syntax.

_CONFLICT_COLUMNS: dict[str, str | tuple[str, ...] | None] = {
    "rera_projects": "rera_number",
    "listings": None,  # UNIQUE(source, source_listing_id) — handled inline
    "kaveri_registrations": "registration_number",
    "igr_transactions": "id",
    "guidance_values": None,
    "news_articles": "cid",
    "surveys": None,  # UNIQUE(survey_no, micro_market_id) — handled inline
    "rtc_records": None,  # UNIQUE(survey_no, rtc_period, rtc_year)
    "khata_records": "khata_no",
    "litigations": None,
    "distressed_opps": None,
    "developer_health": "developer_id",
    "demand_signal": None,  # UNIQUE(micro_market_id, signal_date)
    "deals": None,
    "opportunity_scores": None,
    "developers": "name_normalized",
}

# Tables whose conflict key is a composite UNIQUE constraint.
_COMPOSITE_CONFLICT: dict[str, tuple[str, ...]] = {
    "listings": ("source", "source_listing_id"),
    "surveys": ("survey_no", "micro_market_id"),
    "rtc_records": ("survey_no", "rtc_period", "rtc_year"),
    "demand_signal": ("micro_market_id", "signal_date"),
    "registered_transactions": ("sro", "doc_no", "reg_date"),
}


@dataclass
class WriteResult:
    """Outcome of a single :meth:`IngestWriter.write` call."""
    success: bool
    table: str | None = None
    entity_type: str = ""
    rows_affected: int = 0
    error: str = ""

    def __repr__(self) -> str:
        if self.success:
            return f"WriteResult(OK table={self.table} rows={self.rows_affected})"
        return f"WriteResult(FAIL table={self.table} error={self.error!r})"


class IngestWriter:
    """Handles routing and persistence of :class:`ParsedRecord` instances.

    Each call to :meth:`write` opens a dedicated connection from the engine
    pool and wraps the UPSERT in a SAVEPOINT so that a failure in one record
    never contaminates siblings in the same batch.
    """

    def __init__(self) -> None:
        self._engine = get_engine()

    # ── Public API ─────────────────────────────────────────────────────────────

    def table_for(self, entity_type: str) -> str | None:
        """Return the target-table name for *entity_type*, or ``None``."""
        return _ENTITY_TABLE_MAP.get(entity_type)

    def write(self, record: ParsedRecord) -> bool:
        """Persist *record* to the appropriate table.

        Returns ``True`` on success, ``False`` on failure (already logged).
        """
        result = self.write_detailed(record)
        return result.success

    def write_detailed(self, record: ParsedRecord) -> WriteResult:
        """Like :meth:`write` but returns a structured :class:`WriteResult`."""
        table = self.table_for(record.entity_type)
        if table is None:
            logger.warning("[IngestWriter] unknown entity_type '{}' — skipping", record.entity_type)
            return WriteResult(success=False, entity_type=record.entity_type, error="unknown entity_type")

        sql = self._build_upsert(table, record.data)
        try:
            with self._engine.begin() as conn:
                sp = f"sp_{record.entity_type[:4]}_{abs(hash(record.source_id)) % 10000}"
                conn.execute(text(f"SAVEPOINT {sp}"))
                try:
                    result = conn.execute(text(sql), record.data)
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                except Exception:
                    conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                    conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                    raise
            rows = result.rowcount if result else 0
            return WriteResult(success=True, table=table, entity_type=record.entity_type, rows_affected=rows)
        except Exception as exc:
            logger.error(
                "[IngestWriter] write failed for {} ({}/{}): {}",
                record.entity_type, record.market, record.source_id, exc,
            )
            return WriteResult(success=False, table=table, entity_type=record.entity_type, error=str(exc))

    def write_batch(self, records: list[ParsedRecord]) -> list[WriteResult]:
        """Persist a batch of records in a single transaction with SAVEPOINT isolation."""
        results: list[WriteResult] = []
        try:
            with self._engine.begin() as conn:
                for i, record in enumerate(records):
                    sp = f"batch_sp_{i}"
                    conn.execute(text(f"SAVEPOINT {sp}"))
                    try:
                        table = self.table_for(record.entity_type)
                        if table is None:
                            logger.warning("[IngestWriter] unknown entity_type '{}' in batch — skipping", record.entity_type)
                            results.append(WriteResult(success=False, entity_type=record.entity_type, error="unknown entity_type"))
                            conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                            continue
                        sql = self._build_upsert(table, record.data)
                        result = conn.execute(text(sql), record.data)
                        conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                        rows = result.rowcount if result else 0
                        results.append(WriteResult(success=True, table=table, entity_type=record.entity_type, rows_affected=rows))
                    except Exception as exc:
                        conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                        conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                        logger.error("[IngestWriter] batch record {} failed: {}", i, exc)
                        results.append(WriteResult(success=False, entity_type=record.entity_type, error=str(exc)))
        except Exception as exc:
            logger.error("[IngestWriter] batch transaction failed: {}", exc)
        return results

    # ── SQL builders ────────────────────────────────────────────────────────────

    def _build_upsert(self, table: str, data: dict) -> str:
        """Generate an UPSERT SQL statement for *table* with *data* columns."""
        cols = ", ".join(f'"{c}"' for c in data)
        placeholders = ", ".join(f":{c}" for c in data)
        base = f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders})'

        conflict = self._conflict_target(table)
        if conflict is None:
            return base

        updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in data)
        return f"{base} ON CONFLICT {conflict} DO UPDATE SET {updates}"

    def _conflict_target(self, table: str) -> str | None:
        """Return the ON CONFLICT clause fragment, or ``None`` for plain INSERT."""
        composite = _COMPOSITE_CONFLICT.get(table)
        if composite:
            cols = ", ".join(f'"{c}"' for c in composite)
            return f"({cols})"
        col = _CONFLICT_COLUMNS.get(table)
        if col is None:
            return None
        return f'("{col}")'


# ── Convenience ────────────────────────────────────────────────────────────────


def route_record(record: ParsedRecord) -> bool:
    """One-shot convenience: route a single record through the writer."""
    return IngestWriter().write(record)
