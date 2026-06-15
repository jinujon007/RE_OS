"""
RE_OS — Pipeline Health Smoke Tests (Sprint 40 — GATE-51)
T-784: ≥6 smoke tests guarding the T-780–T-783 fixes.
"""

import re
import subprocess

import pytest

# Tests 1-4 hit the live DB; test 5 hits Docker — skip when infrastructure is absent.
pytestmark = pytest.mark.integration


def _db_available() -> bool:
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


_skip_no_db = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not reachable")


# ── Test 1: Pipeline stage_2_end events appear in agent_runs ──────────────────
# agent_runs schema: agent_name (event name), micro_market, task_type, status
# Pipeline uses insert-only start/end row pairs — no status updates on start rows.
# Scheduled auto-run: Yelahanka (daily). Devanahalli/Hebbal require manual runs.


@_skip_no_db
class TestStageEventsComplete:
    def test_stage_2_end_present_for_all_markets(self):
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            # Yelahanka is auto-scheduled — must have a recent stage_2_end
            row = conn.execute(
                text("""
                SELECT COUNT(*) FROM agent_runs
                WHERE micro_market ILIKE :m AND agent_name = 'stage_2_end'
                  AND started_at >= NOW() - INTERVAL '7 days'
            """),
                {"m": "%Yelahanka%"},
            ).fetchone()
            assert row[0] > 0, (
                "No stage_2_end for Yelahanka in last 7 days — scheduler may be down"
            )

            # Devanahalli: manually run; allow 30-day window
            row = conn.execute(
                text("""
                SELECT COUNT(*) FROM agent_runs
                WHERE micro_market ILIKE :m AND agent_name = 'stage_2_end'
                  AND started_at >= NOW() - INTERVAL '30 days'
            """),
                {"m": "%Devanahalli%"},
            ).fetchone()
            assert row[0] > 0, (
                "No stage_2_end for Devanahalli in last 30 days — run pipeline manually"
            )

            # Hebbal: not yet in the scheduled pipeline — xfail until added to scheduler
            row = conn.execute(
                text("""
                SELECT COUNT(*) FROM agent_runs
                WHERE micro_market ILIKE :m AND agent_name = 'stage_2_end'
            """),
                {"m": "%Hebbal%"},
            ).fetchone()
            if row[0] == 0:
                pytest.xfail(
                    "Hebbal has never completed stage_2 — not in auto-scheduler yet"
                )


# ── Test 2: No zombie runs in recent pipeline activity ────────────────────────
# Pipeline uses insert-only start/end row pairs for stage events. A 'start' row
# stays in_progress indefinitely — that is by design. Zombie detection checks
# NON-pipeline-stage-event rows only (scraper/agent runs) within the last 2 hours.
# Historic stale rows from crashed past runs are excluded to avoid false positives.


@_skip_no_db
class TestNoZombieStages:
    def test_no_stale_in_progress_events(self):
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            # Only check recent non-stage-event rows: started in last 2h but still in_progress after 10 min
            rows = conn.execute(
                text("""
                SELECT COUNT(*) FROM agent_runs
                WHERE status = 'in_progress'
                  AND task_type != 'pipeline_stage_event'
                  AND started_at >= NOW() - INTERVAL '2 hours'
                  AND started_at < NOW() - INTERVAL '10 minutes'
            """)
            ).fetchone()
            assert rows[0] == 0, (
                f"{rows[0]} zombie scraper/agent runs found (in_progress >10 min, started <2h ago). "
                "pipeline_stage_event start rows are excluded — they are insert-only by design."
            )


# ── Test 3: v_market_brief returns rows for all 3 markets ─────────────────────


@_skip_no_db
class TestMarketBriefPopulated:
    def test_all_markets_have_brief(self):
        from utils.db import get_engine
        from sqlalchemy import text

        markets = ["Yelahanka", "Devanahalli", "Hebbal"]
        with get_engine().connect() as conn:
            for market in markets:
                row = conn.execute(
                    text("""
                    SELECT COUNT(*) FROM v_market_brief
                    WHERE micro_market ILIKE :m
                """),
                    {"m": f"%{market}%"},
                ).fetchone()
                assert row[0] >= 1, f"v_market_brief has no row for {market}"


# ── Test 4: avg_psf in v_market_brief within GATE-51 range [3,000–20,000] ─────
# Bounds aligned with GATE-51 criterion (T-943). Portal market rates for
# Bengaluru's mid-market segments consistently fall in this band. Values below
# ₹3,000 indicate guidance-value (IGR) data mixed into listing PSF, or
# insufficient inventory. Values above ₹20,000 suggest luxury/premium segment
# or mis-geocoded listings from higher-price localities.


@_skip_no_db
class TestPSFBounds:
    def test_avg_listing_psf_within_bounds(self):
        from utils.db import get_engine
        from sqlalchemy import text
        from config.gate_criteria import GATE51_PSF_MIN, GATE51_PSF_MAX

        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                SELECT micro_market, avg_listing_psf
                FROM v_market_brief
                WHERE total_projects >= 10
            """)
            ).fetchall()

        markets_checked = 0
        for market, psf in rows:
            if psf is None:
                # No listing data for this market — data availability issue, not a PSF bug.
                # avg_listing_psf is listing-derived; markets with no scraped listings will be NULL.
                continue
            assert GATE51_PSF_MIN <= psf <= GATE51_PSF_MAX, (
                f"{market}: avg_listing_psf={psf} outside "
                f"GATE-51 range [{GATE51_PSF_MIN}, {GATE51_PSF_MAX}] — "
                "portal market rates should fall in this band"
            )
            markets_checked += 1

        assert markets_checked >= 1, (
            "No markets had non-NULL avg_listing_psf — listing scraper may be broken"
        )


# ── Test 5: Scheduler healthcheck command exits 0 ─────────────────────────────


def _docker_running() -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "re_os_scheduler", "--format", "{{.State.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and "running" in result.stdout.lower()
    except Exception:
        return False


@pytest.mark.skipif(
    not _docker_running(), reason="re_os_scheduler container not running"
)
class TestSchedulerHealthcheck:
    def test_scheduler_healthcheck_exits_zero(self):
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "re_os_scheduler",
                "--format",
                "{{.State.Health.Status}}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        status = result.stdout.strip()
        assert status == "healthy", (
            f"Scheduler health status: '{status}' — expected 'healthy'"
        )


# ── Test 6: Discord notifier raises ConfigurationError when webhook unset ──────


class TestDiscordConfigError:
    def test_raises_when_webhook_unset(self):
        import os
        from utils.discord_notifier import ConfigurationError, send

        old_url = os.environ.pop("DISCORD_WEBHOOK_URL", None)
        for key in [
            "DISCORD_WEBHOOK_SYSTEM",
            "DISCORD_WEBHOOK_RERA_YELAHANKA",
        ]:
            os.environ.pop(key, None)

        try:
            with pytest.raises(ConfigurationError):
                send("system", "T-784 test", "health check")
        finally:
            if old_url:
                os.environ["DISCORD_WEBHOOK_URL"] = old_url
