"""
RE_OS — Pipeline Health Smoke Tests (Sprint 40 — GATE-51)
T-784: ≥6 smoke tests guarding the T-780–T-783 fixes.
"""
import re
import subprocess
import time

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


# ── Test 1: All 3 markets appear in agent_runs with stage_2_end completed ──────

@_skip_no_db
class TestStageEventsComplete:
    def test_stage_2_end_present_for_all_markets(self):
        from utils.db import get_engine
        from sqlalchemy import text

        markets = ["Yelahanka", "Devanahalli", "Hebbal"]
        with get_engine().connect() as conn:
            for market in markets:
                row = conn.execute(text("""
                    SELECT COUNT(*) FROM agent_runs
                    WHERE market ILIKE :m AND event_type = 'stage_2_end'
                      AND started_at >= NOW() - INTERVAL '7 days'
                """), {"m": f"%{market}%"}).fetchone()
                assert row[0] > 0, f"No stage_2_end found for {market} in last 7 days"


# ── Test 2: No stage event stays in_progress >10 min ───────────────────────────

@_skip_no_db
class TestNoZombieStages:
    def test_no_stale_in_progress_events(self):
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT COUNT(*) FROM agent_runs
                WHERE status = 'in_progress'
                  AND started_at < NOW() - INTERVAL '10 minutes'
            """)).fetchone()
            assert rows[0] == 0, f"{rows[0]} zombie stage_events found (in_progress >10 min)"


# ── Test 3: v_market_brief returns rows for all 3 markets ─────────────────────

@_skip_no_db
class TestMarketBriefPopulated:
    def test_all_markets_have_brief(self):
        from utils.db import get_engine
        from sqlalchemy import text

        markets = ["Yelahanka", "Devanahalli", "Hebbal"]
        with get_engine().connect() as conn:
            for market in markets:
                row = conn.execute(text("""
                    SELECT COUNT(*) FROM v_market_brief
                    WHERE micro_market ILIKE :m
                """), {"m": f"%{market}%"}).fetchone()
                assert row[0] >= 1, f"v_market_brief has no row for {market}"


# ── Test 4: avg_psf in v_market_brief between 1,500 and 25,000 ────────────────

@_skip_no_db
class TestPSFBounds:
    def test_avg_listing_psf_within_bounds(self):
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT micro_market, avg_listing_psf
                FROM v_market_brief
                WHERE total_projects >= 10
            """)).fetchall()
            for market, psf in rows:
                assert psf is not None, f"{market}: avg_listing_psf is NULL"
                assert 1500 <= psf <= 25000, (
                    f"{market}: avg_listing_psf={psf} outside [1500, 25000] — "
                    "catches ₹10,148-class outlier bug"
                )


# ── Test 5: Scheduler healthcheck command exits 0 ─────────────────────────────

def _docker_running() -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "re_os_scheduler",
             "--format", "{{.State.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and "running" in result.stdout.lower()
    except Exception:
        return False


@pytest.mark.skipif(not _docker_running(), reason="re_os_scheduler container not running")
class TestSchedulerHealthcheck:
    def test_scheduler_healthcheck_exits_zero(self):
        result = subprocess.run(
            ["docker", "inspect", "re_os_scheduler",
             "--format", "{{.State.Health.Status}}"],
            capture_output=True, text=True, timeout=30,
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
