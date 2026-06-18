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
from config.metrics import dead_letter_retry_total

logger = logging.getLogger("re_os.dead_letter_queue")

_RETRY_BATCH_SIZE = 20
_DLQ_ALERT_THRESHOLD = 50  # Discord alert when >50 records in queue


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


def check_queue_depth_and_alert(engine: Engine | None = None) -> int:
    """Check DLQ depth and send Discord alert if above threshold."""
    depth = get_queue_depth(engine)
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
