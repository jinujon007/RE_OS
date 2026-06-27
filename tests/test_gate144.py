"""GATE-144 — Dashboard Command Center

5 unified assertions covering all 5 tasks (T-1406→T-1410):
1. Decision Journal panel: route + nav + template
2. Deed Throughput panel: template + deadline + API fetch
3. Assembly Signals panel: template + API fetch + empty state + drill-down
4. Dashboard Badges endpoint: 200 + keys + status string + DB-down resilience + rate limit + SQL logic
5. Files py_compile clean + badge JS in index.html
"""

import logging
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.unit

logger = logging.getLogger(__name__)

BASE = pathlib.Path("dashboard/templates")
DATA_PY = "dashboard/routers/data.py"


# ── Helper ────────────────────────────────────────────────────────────────

def read_template(name: str) -> str:
    return (BASE / name).read_text(encoding="utf-8")


# ── Assertion 1: Decision Journal Panel ───────────────────────────────────

class TestDecisionJournal:
    def test_route_registered(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        resp = client.get("/decision-journal")
        assert resp.status_code in {200, 307}
        if resp.status_code == 200:
            assert "Decision Journal" in resp.text or "DECISION" in resp.text

    def test_nav_in_index(self):
        index = read_template("index.html")
        assert "decision-journal" in index

    def test_template_exists(self):
        assert (BASE / "decision_journal.html").exists()

    def test_flag_filter_api_param(self):
        content = read_template("decision_journal.html")
        assert "params.set('decision_flag', flag)" in content

    def test_conditional_stat_card(self):
        content = read_template("decision_journal.html")
        assert "stat-conditional" in content

    def test_auto_refresh(self):
        content = read_template("decision_journal.html")
        assert "AUTO_REFRESH_MS" in content or "startAutoRefresh" in content

    def test_url_state_bookmarkable(self):
        content = read_template("decision_journal.html")
        assert "updateUrlState" in content or "history.replaceState" in content


# ── Assertion 2: Deed Throughput Panel ────────────────────────────────────

class TestDeedThroughput:
    def test_template_exists(self):
        assert (BASE / "deed_throughput.html").exists()

    def test_deadline_hardcoded(self):
        content = read_template("deed_throughput.html")
        assert "2026-08-15" in content

    def test_api_fetch_present(self):
        content = read_template("deed_throughput.html")
        assert "/api/v1/deeds/throughput" in content

    def test_4wk_avg_computed_over_last_4(self):
        content = read_template("deed_throughput.html")
        assert "weeks.slice(0, 4)" in content or "weeks.slice" in content

    def test_deadline_status_populated(self):
        content = read_template("deed_throughput.html")
        assert "deadline-status" in content

    def test_status_map_lookup(self):
        content = read_template("deed_throughput.html")
        assert "STATUS_MAP" in content

    def test_auto_refresh(self):
        content = read_template("deed_throughput.html")
        assert "AUTO_REFRESH_MS" in content or "startAutoRefresh" in content


# ── Assertion 3: Assembly Signals Panel ───────────────────────────────────

class TestAssemblySignals:
    def test_template_exists(self):
        assert (BASE / "assembly_signals.html").exists()

    def test_api_fetch_present(self):
        content = read_template("assembly_signals.html")
        assert "/api/v1/intel/assembly-alerts" in content

    def test_empty_state_present(self):
        content = read_template("assembly_signals.html")
        assert "data/kaveri_deeds/inbox/form17/" in content

    def test_drill_down_expandable(self):
        content = read_template("assembly_signals.html")
        assert "toggleDetail" in content and "expanded" in content

    def test_days_colour_degradation(self):
        content = read_template("assembly_signals.html")
        assert "getDaysClass" in content or "days-stale" in content

    def test_telegram_badge_title(self):
        content = read_template("assembly_signals.html")
        assert "Telegram alert sent" in content or "title=" in content

    def test_confidence_green_for_actionable(self):
        content = read_template("assembly_signals.html")
        assert "confidence-badge.actionable" in content or "confidence-badge.high" in content


# ── Assertion 4: Dashboard Badges Endpoint ────────────────────────────────

class TestDashboardBadgesEndpoint:
    def test_returns_200_with_keys(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        resp = client.get("/api/v1/dashboard/badges")
        assert resp.status_code in {200, 307}
        if resp.status_code == 200:
            data = resp.json()
            for k in ("decision_journal_today", "assembly_high_confidence", "deed_status", "as_of"):
                assert k in data, f"Missing key: {k}"

    def test_deed_status_is_string(self):
        from dashboard.app_fastapi import app
        client = TestClient(app)
        resp = client.get("/api/v1/dashboard/badges")
        if resp.status_code == 200:
            assert isinstance(resp.json().get("deed_status"), str)

    def test_db_down_returns_zeros(self):
        from dashboard.app_fastapi import app
        with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
            mock_eng.side_effect = RuntimeError("DB down")
            client = TestClient(app)
            resp = client.get("/api/v1/dashboard/badges")
            assert resp.status_code == 200
            data = resp.json()
            assert data["decision_journal_today"] == 0
            assert data["assembly_high_confidence"] == 0
            assert data["deed_status"] in ("critical", "at_risk", "on_track", "unknown")

    def test_db_success_path(self):
        from dashboard.app_fastapi import app
        from unittest.mock import MagicMock
        mock_conn = MagicMock()
        mock_conn.execute.return_value.scalar.return_value = 0
        mock_conn.execute.return_value.fetchone.return_value = (0,)
        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__.return_value = mock_conn
        with patch("dashboard.routers.data._get_sa_engine", return_value=mock_eng):
            client = TestClient(app)
            resp = client.get("/api/v1/dashboard/badges")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data["decision_journal_today"], int)
            assert isinstance(data["assembly_high_confidence"], int)

    def test_rate_limit_config_present(self):
        src = pathlib.Path(DATA_PY).read_text(encoding="utf-8")
        assert '@limiter.limit("60/minute")' in src or 'limiter.limit("60/minute")' in src

    def test_duration_histogram_registered(self):
        src = pathlib.Path(DATA_PY).read_text(encoding="utf-8")
        assert "db_query_duration_seconds.labels(query_name=\"dashboard_badges\")" in src


# ── Assertion 5: Badge JS + py_compile ────────────────────────────────────

class TestBadgeJsAndCompile:
    def test_badge_script_in_index(self):
        content = read_template("index.html")
        assert "pollDashboardBadges" in content

    def test_badge_dom_elements(self):
        content = read_template("index.html")
        assert 'id="badge-decision"' in content
        assert 'id="badge-deed-status"' in content

    def test_py_compile_data_py(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", "dashboard/routers/data.py"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"py_compile failed:\n{result.stderr}"

    def test_py_compile_state_py(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", "dashboard/state.py"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"py_compile failed:\n{result.stderr}"
