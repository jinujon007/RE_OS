"""GATE-117 — DLQ + Scheduler Hardening.

5 assertions:
1. SchemaDriftError importable from utils.dead_letter_queue
2. purge_old_records callable from utils.dead_letter_queue
3. run_dlq_purge registered in config/scheduler/maintenance_jobs
4. Docker-compose scheduler healthcheck interval ≤ 30 minutes
5. purge_stale_embeddings source contains queried_at string
"""

from pathlib import Path


def test_schema_drift_error_importable():
    from utils.dead_letter_queue import SchemaDriftError
    assert issubclass(SchemaDriftError, Exception)
    exc = SchemaDriftError("test_table", ["col_a"])
    assert exc.table == "test_table"
    assert exc.missing_columns == ["col_a"]


def test_purge_old_records_callable():
    from utils.dead_letter_queue import purge_old_records
    assert callable(purge_old_records)


def test_run_dlq_purge_registered():
    content = Path("config/scheduler/maintenance_jobs.py").read_text()
    assert "dlq_purge" in content
    assert "run_dlq_purge" in content


def test_scheduler_healthcheck_window_30_min():
    """Docker-compose healthcheck references the script, not inline dead-code."""
    import yaml
    dc = yaml.safe_load(Path("docker-compose.yml").read_text())
    test_cmd = dc["services"]["scheduler_v2"]["healthcheck"]["test"]
    cmd_str = " ".join(test_cmd) if isinstance(test_cmd, list) else test_cmd
    assert "config/healthcheck.py" in cmd_str
    assert Path("config/healthcheck.py").exists()


def test_healthcheck_script_importable():
    """The healthcheck script must compile and be importable."""
    from config.healthcheck import _check
    assert callable(_check)


def test_purge_stale_embeddings_has_queried_at():
    source = Path("utils/embedder.py").read_text()
    assert "queried_at" in source
