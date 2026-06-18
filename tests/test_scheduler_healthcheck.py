"""Tests for scheduler healthcheck window (GATE-117 / T-1274).

Validates both the YAML config AND the actual healthcheck script logic.
The previous version only checked string presence of "30 minutes" — which
would pass even if the healthcheck logic was dead code (R1 F-1).
"""

from pathlib import Path


def test_healthcheck_script_exists():
    """The healthcheck script must exist and be importable."""
    assert Path("config/healthcheck.py").exists()
    import py_compile
    py_compile.compile("config/healthcheck.py", doraise=True)


def test_healthcheck_script_exit_codes():
    """Verify the _check() function returns correct exit codes in known states.

    - No DB connection: should return 0 (degraded pass, not restart-worthy)
    - Heartbeat found: should return 0 (healthy)
    - Heartbeat stale with DB reachable: should return 1 (unhealthy)
    """
    from unittest.mock import patch, MagicMock
    from sqlalchemy import text

    from config.healthcheck import _check

    # Case 1: DB unreachable (get_engine raises) → degraded pass (0)
    with patch("utils.db.get_engine", side_effect=Exception("DB down")):
        assert _check() == 0, "DB-down should return 0 (degraded pass)"

    # Case 2: Heartbeat found → healthy (0)
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = (1,)
    with patch("utils.db.get_engine", return_value=mock_engine):
        assert _check() == 0, "Heartbeat found should return 0"

    # Case 3: Heartbeat stale (no row returned) → unhealthy (1)
    mock_conn2 = MagicMock()
    mock_engine2 = MagicMock()
    mock_engine2.connect.return_value.__enter__.return_value = mock_conn2
    mock_conn2.execute.return_value.fetchone.return_value = None
    with patch("utils.db.get_engine", return_value=mock_engine2):
        assert _check() == 1, "Heartbeat stale should return 1"


def test_healthcheck_docker_compose_refs_script():
    """docker-compose.yml must reference the script, not an inline command."""
    import yaml
    dc = yaml.safe_load(Path("docker-compose.yml").read_text())
    test_cmd = dc["services"]["scheduler_v2"]["healthcheck"]["test"]
    cmd_str = " ".join(test_cmd) if isinstance(test_cmd, list) else test_cmd
    assert "config/healthcheck.py" in cmd_str, (
        f"healthcheck must reference config/healthcheck.py, got: {cmd_str[:100]}"
    )
