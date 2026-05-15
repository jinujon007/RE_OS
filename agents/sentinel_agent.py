import os
from datetime import datetime, timedelta, timezone

import psycopg2


def _get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def get_last_scheduled_run() -> dict | None:
    """Returns most recent scheduler-triggered agent_run, or latest run if trigger column absent."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'agent_runs'
            """
        )
        columns = {row[0] for row in cur.fetchall()}

        base_select = """
            SELECT micro_market, started_at, status, duration_seconds
            FROM agent_runs
        """

        if "triggered_by" in columns:
            query = (
                base_select
                + """
                WHERE triggered_by = 'scheduler'
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
        else:
            query = (
                base_select
                + """
                ORDER BY started_at DESC
                LIMIT 1
                """
            )

        cur.execute(query)
        row = cur.fetchone()

        if not row:
            return None

        return {
            "micro_market": row[0],
            "started_at": row[1].isoformat() if row[1] else None,
            "status": row[2],
            "duration_seconds": row[3],
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


def get_next_scheduled_run() -> dict:
    """Calculates next 2AM UTC run from current time."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=2, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    delta = target - now
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)

    return {
        "next_run_utc": target.isoformat(),
        "in_hours": hours,
        "in_minutes": minutes,
        "label": f"in {hours}h {minutes}m" if hours > 0 else f"in {minutes}m",
    }
