"""
RE_OS — GCC Hiring Snapshot Ingest Plugin (GATE-94, T-1152)

Ingests weekly Naukri job-posting counts per tracked GCC employer into the
gcc_hiring_snapshots table.  Also computes WoW delta and triggers Discord
alert when posting count changes by >=25%.

The existing GCCPlugin in gcc_plugin.py reads from gcc_hiring_snapshots and
promotes live-snapshot employers (demoting seed data to data_source='seed').

Entity type: gcc_hiring_snapshot → gcc_hiring_snapshots table.
"""

from __future__ import annotations

from datetime import date, timedelta

from loguru import logger

from ingest.base import DataPlugin, ParsedRecord, ValidationResult


class GccHiringPlugin(DataPlugin):
    """Weekly snapshot of job-posting counts per tracked GCC employer.

    Scrapes Naukri public search for each tracked employer and upserts
    one record per (employer, location, snapshot_date) combination.
    """

    plugin_id = "gcc_hiring_snapshot"
    source_id = "gcc_hiring_naukri"

    def run(self, market: str | None = None) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []
        try:
            from scrapers.gcc_hiring_scraper import run_snapshot
            results = run_snapshot()
        except Exception as exc:
            logger.warning("[GccHiringPlugin] scraper failed: {}", exc)
            return records

        today = date.today()
        for r in results:
            posting_count = r.get("posting_count", 0)
            if posting_count < 0:
                posting_count = 0
            data = {
                "employer": r["employer"],
                "location": r.get("hub", "Bengaluru"),
                "posting_count": posting_count,
                "snapshot_date": today.isoformat(),
                "source": r.get("source", "naukri_search"),
            }
            source_id = f"ghs_{r['employer'].lower().replace(' ', '_')}_{today.isoformat()}_{r.get('hub', 'blr')[:20]}"
            records.append(
                ParsedRecord(
                    entity_type="gcc_hiring_snapshot",
                    source_id=source_id,
                    market=market or "Bengaluru",
                    data=data,
                    confidence=0.8 if posting_count > 0 else 0.3,
                )
            )

        self._check_wow_delta(records)
        return records

    def validate(self, record: ParsedRecord) -> ValidationResult:
        errors = []
        if not record.data.get("employer"):
            errors.append("employer required")
        if record.data.get("posting_count") is None:
            errors.append("posting_count required")
        return ValidationResult(valid=not errors, errors=errors)

    def _check_wow_delta(self, records: list[ParsedRecord]) -> None:
        """Check WoW posting count delta for each employer; alert if >=25%.

        Batches all deltas into a single Discord message to avoid channel spam.
        """
        try:
            from utils.db import get_engine
            from sqlalchemy import text
            from utils.discord_notifier import send

            today = date.today()
            last_week = today - timedelta(days=7)
            two_weeks_ago = today - timedelta(days=14)
            alert_lines: list[str] = []

            with get_engine(pool_size=1, max_overflow=0).connect() as conn:
                for rec in records:
                    employer = rec.data["employer"]
                    location = rec.data["location"]
                    current = rec.data.get("posting_count", 0)

                    prev_row = conn.execute(
                        text("""
                            SELECT posting_count FROM gcc_hiring_snapshots
                            WHERE employer = :emp AND location = :loc
                              AND snapshot_date BETWEEN :from_d AND :to_d
                            ORDER BY snapshot_date DESC LIMIT 1
                        """),
                        {"emp": employer, "loc": location, "from_d": last_week, "to_d": today - timedelta(days=1)},
                    ).fetchone()

                    if prev_row is None:
                        prev_row = conn.execute(
                            text("""
                                SELECT posting_count FROM gcc_hiring_snapshots
                                WHERE employer = :emp AND location = :loc
                                  AND snapshot_date >= :from_d
                                ORDER BY snapshot_date DESC LIMIT 1
                            """),
                            {"emp": employer, "loc": location, "from_d": two_weeks_ago},
                        ).fetchone()

                    prev_count = int(prev_row[0]) if prev_row else 0
                    if prev_count > 0 and current > 0:
                        delta_pct = abs(current - prev_count) / prev_count * 100
                        if delta_pct >= 25:
                            direction = "up" if current > prev_count else "down"
                            alert_lines.append(
                                f"{employer} ({location}): {direction} {delta_pct:.0f}% — {prev_count} → {current}"
                            )

            if alert_lines:
                send("gcc_intel", f"⚠️ GCC Hiring WoW ({len(alert_lines)} changes)",
                    "\n".join(alert_lines))
        except Exception as exc:
            logger.warning("[GccHiringPlugin] WoW delta check failed: {}", exc)
