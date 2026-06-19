"""GATE-122 declaration — Conditional Gates Live Closure Tooling.

5 assertions (code-verifiable without live DB):
(1) scripts/process_deed_inbox.py importable; --help exits 0
(2) scripts/check_conditional_gates.py evaluates gates with mocked DB
(3) /api/v1/ops/conditional-gates route registered in FastAPI app
(4) kaveri_form17_weekly scheduler job registered
(5) KaveriForm17Plugin importable from ingest.plugins
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_assertion1_script_importable_and_help():
    """A1: scripts/process_deed_inbox.py --help exits 0."""
    script = REPO_ROOT / "scripts" / "process_deed_inbox.py"
    assert script.exists(), f"Missing: {script}"
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert result.returncode == 0, f"--help failed: {result.stderr}"
    assert "usage:" in result.stdout.lower()


def test_assertion2_check_script_gate_evaluation():
    """A2: scripts/check_conditional_gates.py evaluates gates with mocked DB
    respecting per-component thresholds (GATE-93: ledger>=10 AND tenders>=20)."""
    from scripts.check_conditional_gates import evaluate_gates

    with patch("scripts.check_conditional_gates.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_eng.return_value.dispose = MagicMock()

        def make_row(val):
            r = MagicMock()
            r.__getitem__ = lambda s, idx: val if idx == 0 else 0
            return r

        # 7 sub-checks across 5 gates:
        # GATE-91: 215 >= 200 PASS
        # GATE-92: 150 >= 100 PASS
        # GATE-93: ledger 15 >= 10 PASS, tenders 25 >= 20 PASS
        # GATE-94: gcc 12 >= 10 PASS, dc 11 >= 10 PASS
        # GATE-95: 14 >= 10 PASS
        mock_conn.execute.return_value.fetchone.side_effect = [
            make_row(215),   # GATE-91
            make_row(150),   # GATE-92
            make_row(15),    # GATE-93 ledger (>=10)
            make_row(25),    # GATE-93 tenders (>=20)
            make_row(12),    # GATE-94 gcc (>=10)
            make_row(11),    # GATE-94 dc (>=10)
            make_row(14),    # GATE-95
        ]

        gates = evaluate_gates()
        assert len(gates) == 5
        for g in gates:
            assert g["status"] == "PASS", f"{g['gate']} should PASS: {g}"
        # Verify GATE-93 sub-checks
        g93 = [g for g in gates if g["gate"] == "GATE-93"][0]
        assert len(g93["checks"]) == 2
        assert all(c["passed"] for c in g93["checks"]), f"GATE-93 sub-checks failed: {g93['checks']}"
        # Verify GATE-94 sub-checks
        g94 = [g for g in gates if g["gate"] == "GATE-94"][0]
        assert len(g94["checks"]) == 2
        assert all(c["passed"] for c in g94["checks"]), f"GATE-94 sub-checks failed: {g94['checks']}"


def test_assertion3_conditional_gates_route_registered():
    """A3: /api/v1/ops/conditional-gates route present in FastAPI app (route inspection, no HTTP call)."""
    from dashboard.app_fastapi import app

    route_paths = []
    for route in app.routes:
        if hasattr(route, "path"):
            route_paths.append(route.path)

    matching = [p for p in route_paths if "conditional-gates" in p]
    assert matching, (
        f"No route containing 'conditional-gates' found. Registered routes: {[p for p in route_paths if 'ops' in p]}"
    )

    ops_path = REPO_ROOT / "dashboard" / "routers" / "ops.py"
    ops_content = ops_path.read_text(encoding="utf-8")
    assert "conditional_gates" in ops_content and "gates" in ops_content, (
        "conditional_gates endpoint + gates response key expected in ops.py"
    )


def test_assertion4_scheduler_job_registered():
    """A4: kaveri_form17_weekly job registered in scheduler source."""
    scheduler_file = REPO_ROOT / "config" / "scheduler" / "maintenance_jobs.py"
    assert scheduler_file.exists()
    text = scheduler_file.read_text()
    assert 'id="kaveri_form17_weekly"' in text, "kaveri_form17_weekly job ID not found"
    assert "run_form17_inbox_scan" in text, "run_form17_inbox_scan function not found"


def test_assertion5_plugin_importable():
    """A5: KaveriForm17Plugin importable from ingest.plugins."""
    from ingest.plugins import KaveriForm17Plugin

    assert KaveriForm17Plugin.plugin_id == "kaveri_form17"
    assert callable(KaveriForm17Plugin)
