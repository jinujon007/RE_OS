"""
RE_OS — Dead Letter Queue for failed ingest records.
Manages retry and inspection of failed DB writes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from utils.db import get_engine
from config.metrics import dead_letter_retry_total, dead_letter_queue_depth_gauge

logger = logging.getLogger("re_os.dead_letter_queue")

_RETRY_BATCH_SIZE = 20
_DLQ_ALERT_THRESHOLD = 50  # Discord alert when >50 records in queue


def _sync_dlq_gauge(engine: Engine | None = None) -> None:
    """Synchronise DLQ depth gauge with actual DB count.

    Corrects any drift between the gauge and the real queue depth.
    Called after retry batches and purge operations. Also called on
    every check_queue_depth_and_alert() invocation.

    Uses the 'unknown' entity_type label bucket for aggregate depth.
    If get_queue_depth() fails (DB down), the prior gauge value is
    preserved (no-op on Prometheus side since .set() is not called).
    Falls back to 0 on empty queue.
    """
    depth = get_queue_depth(engine)
    dead_letter_queue_depth_gauge.labels(entity_type="unknown").set(depth)

# Mapping from DLQ entity_type to the DB table used by _replay_record.
# Used for schema validation: we check that incoming record keys exist
# as columns on the target table before attempting the upsert.
_ENTITY_TABLE_MAP: dict[str, str] = {
    "rera_project": "rera_projects",
    "rera_projects": "rera_projects",
    "registration": "registered_transactions",
    "registered_transaction": "registered_transactions",
}


class SchemaDriftError(Exception):
    """Raised when a DLQ replay record has keys that don't match the live table schema.

    Attributes:
        table — the target DB table name
        missing_columns — column names expected but absent from the record
    """
    def __init__(self, table: str, missing_columns: list[str]):
        self.table = table
        self.missing_columns = missing_columns
        super().__init__(f"Schema drift on '{table}': missing columns {missing_columns}")


def _fetch_table_columns(conn, table: str) -> set[str]:
    """Query PostgreSQL information_schema for live column names.

    Returns a set of column names for the given table. Falls back to empty set
    on any error (caller must handle gracefully).
    """
    try:
        rows = conn.execute(
            text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = :table
            """),
            {"table": table},
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        logger.warning("[DLQ] Failed to fetch schema for table '%s'", table)
        return set()


def _fetch_db_generated_columns(conn, table: str) -> set[str]:
    """Query information_schema for columns that are DB-generated (have defaults, are identity, or generated).

    These columns are excluded from schema-drift validation because the DB
    populates them automatically — the record is not expected to supply values.
    Falls back to empty set on error (validation degrades to conservative mode).
    """
    try:
        rows = conn.execute(
            text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = :table
                  AND (column_default IS NOT NULL
                       OR is_generated = 'ALWAYS'
                       OR is_identity = 'YES')
            """),
            {"table": table},
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        logger.warning("[DLQ] Failed to fetch generated columns for table '%s'", table)
        return set()


def _validate_schema(conn, entity_type: str, raw: dict) -> None:
    """Validate that all required columns for the entity_type exist in the record.

    Raises SchemaDriftError if any live column (that is NOT DB-generated) is missing
    from the incoming record. Dynamically discovers DB-generated columns via
    information_schema instead of maintaining a static whitelist — schema evolution
    safe (new identity/default columns are auto-excluded).

    This is a best-effort guard, not an exhaustive constraint check:
    - Only checks columns that the record COULD supply.
    - Does not validate data types, NOT NULL without default, or CHECK constraints.
    """
    table = _ENTITY_TABLE_MAP.get(entity_type)
    if table is None:
        return

    live_columns = _fetch_table_columns(conn, table)
    if not live_columns:
        return

    auto_columns = _fetch_db_generated_columns(conn, table)
    # Also skip common system columns that information_schema may not mark as generated
    auto_columns.update({"parcel_id"})

    record_keys = {k.lower() for k in raw.keys()}
    missing = sorted(
        c for c in live_columns
        if c.lower() not in record_keys and c.lower() not in auto_columns
    )
    if missing:
        raise SchemaDriftError(table, missing)


def get_failed_records(
    engine: Engine | None = None,
    limit: int = 50,
    retry_count_max: int = 3,
) -> list[dict[str, Any]]:
    """Return the latest failed records from the dead letter queue."""
    if engine is None:
        engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, entity_type, source_id, error_text, plugin_id,
                       failed_at, retry_count
                FROM ingest_failed_records
                WHERE retry_count < :max_retry
                ORDER BY failed_at DESC
                LIMIT :lim
            """),
            {"max_retry": retry_count_max, "lim": limit},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_queue_depth(engine: Engine | None = None) -> int:
    """Return total count of records with retry_count < max."""
    if engine is None:
        engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM ingest_failed_records WHERE retry_count < 3"),
        ).scalar()
    return row or 0


def purge_old_records(
    engine: Engine | None = None,
    max_age_days: int = 30,
) -> int:
    """Delete DLQ records that have permanently failed and are older than max_age_days.

    Only deletes records where retry_count >= max_retries (i.e. permanently failed,
    not pending retry). Returns the number of deleted rows.
    """
    if engine is None:
        engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                DELETE FROM ingest_failed_records
                WHERE failed_at < NOW() - (:days || ' days')::interval
                  AND retry_count >= 3
            """),
            {"days": max_age_days},
        )
        deleted = result.rowcount or 0
        if deleted > 100:
            try:
                from utils.discord_notifier import send_ops_alert
                send_ops_alert(
                    "DLQ_HIGH_PURGE",
                    f"DLQ auto-purge deleted {deleted} records (>100 threshold) — "
                    f"possible abnormal failure rate.",
                )
            except Exception as exc:
                logger.warning("[DLQ] Failed to send high-purge alert: %s", exc)
        logger.info("[DLQ] Purged %d old failed records (>%d days)", deleted, max_age_days)
    if deleted > 0:
        _sync_dlq_gauge(engine)
    return deleted


def check_queue_depth_and_alert(engine: Engine | None = None) -> int:
    """Check DLQ depth and send Discord alert if above threshold.
    
    Synchronises the gauge on every call to correct drift.
    """
    depth = get_queue_depth(engine)
    dead_letter_queue_depth_gauge.labels(entity_type="unknown").set(depth)
    if depth > _DLQ_ALERT_THRESHOLD:
        try:
            from utils.discord_notifier import send_ops_alert
            send_ops_alert(
                "DLQ_THRESHOLD",
                f"Dead letter queue has {depth} unprocessed records "
                f"(threshold: {_DLQ_ALERT_THRESHOLD}). Inspect via GET /api/v1/ops/failed-records.",
            )
        except Exception as exc:
            logger.warning("[DLQ] Failed to send threshold alert: %s", exc)
    return depth


def retry_failed_records(
    engine: Engine | None = None,
    max_retries: int = 3,
    batch_size: int = _RETRY_BATCH_SIZE,
) -> dict[str, Any]:
    """Re-attempt failed ingest records up to max_retries times.

    Increments retry_count for each attempt. Records with retry_count >=
    max_retries are left for manual inspection.

    Returns:
        dict with keys: attempted, succeeded, failed, errors
    """
    if engine is None:
        engine = get_engine()
    attempted = succeeded = failed = 0
    errors: list[str] = []

    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT id, entity_type, source_id, raw_data::text
                FROM ingest_failed_records
                WHERE retry_count < :max_retry
                ORDER BY failed_at ASC
                LIMIT :batch
            """),
            {"max_retry": max_retries, "batch": batch_size},
        ).fetchall()

        for i, row in enumerate(rows):
            attempted += 1
            row_id = row._mapping["id"]
            entity_type = row._mapping["entity_type"]
            try:
                raw = json.loads(row._mapping["raw_data"])
            except (json.JSONDecodeError, TypeError):
                raw = {}
            sp = f"sp_dlq_retry_{i}"
            try:
                conn.execute(text(f"SAVEPOINT {sp}"))
                _replay_record(conn, entity_type, raw)
                conn.execute(
                    text("UPDATE ingest_failed_records SET retry_count = retry_count + 1 WHERE id = :rid"),
                    {"rid": row_id},
                )
                conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                dead_letter_retry_total.labels(entity_type=entity_type, result="success").inc()
                succeeded += 1
            except SchemaDriftError as sde:
                conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                logger.error("[DLQ] Schema drift: %s — skipping record %s", sde, row_id)
                try:
                    from utils.discord_notifier import send_ops_alert
                    send_ops_alert(
                        "DLQ_SCHEMA_DRIFT",
                        f"DLQ schema drift on '{sde.table}' — manual intervention required. "
                        f"Record {row_id} skipped. Missing columns: {sde.missing_columns}",
                    )
                except Exception as alert_exc:
                    logger.warning("[DLQ] Failed to send schema drift alert: %s", alert_exc)
                conn.execute(
                    text("UPDATE ingest_failed_records SET retry_count = retry_count + 1, error_text = :err WHERE id = :rid"),
                    {"err": f"SchemaDriftError: {sde}"[:500], "rid": row_id},
                )
                dead_letter_retry_total.labels(entity_type=entity_type, result="schema_drift").inc()
                failed += 1
                errors.append(f"{entity_type}/{row_id}: SCHEMA_DRIFT — {sde}")
            except Exception as exc:
                conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp}"))
                conn.execute(text(f"RELEASE SAVEPOINT {sp}"))
                conn.execute(
                    text("UPDATE ingest_failed_records SET retry_count = retry_count + 1, error_text = :err WHERE id = :rid"),
                    {"err": f"{type(exc).__name__}: {exc}"[:500], "rid": row_id},
                )
                dead_letter_retry_total.labels(entity_type=entity_type, result="failed").inc()
                failed += 1
                errors.append(f"{entity_type}/{row_id}: {exc}")

    if attempted > 0:
        _sync_dlq_gauge(engine)
    return {
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "errors": errors[:5],
    }


def _replay_record(conn, entity_type: str, raw: dict) -> None:
    """Replay one record by routing to source-of-truth upsert methods.

    Delegates to DBOrganizer's upsert methods rather than duplicating SQL.
    If DBOrganizer schema evolves, replay stays in sync automatically.
    """
    _validate_schema(conn, entity_type, raw)
    from utils.db_organizer import DBOrganizer

    market = raw.get("market") or raw.get("micro_market") or "Yelahanka"
    org = DBOrganizer()

    if entity_type in ("rera_project", "rera_projects"):
        market_id = org._get_market_id(conn, raw)
        org._upsert_developer(conn, raw)
        org._upsert_project(conn, raw, None, market_id)
    elif entity_type in ("registration", "registered_transaction"):
        market_id = org._get_market_id(conn, raw)
        org._insert_registration(conn, raw, market_id)
    else:
        raise ValueError(f"Unknown entity_type for replay: {entity_type}")
