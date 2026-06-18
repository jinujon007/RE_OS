"""GATE-108 — Scheduler Isolation + Production Infrastructure.

Five assertions:
1. docker-compose.yml contains `re_os_scheduler_v2` service name
2. REDIS_PASSWORD enforcement logic present in dashboard/state.py
3. Dockerfile contains `AS builder` stage
4. scrapers/news_scout.py compiles with 0 ruff errors
5. alembic/versions/0064_ingest_failed_records.py exists
"""

from pathlib import Path
import subprocess

COMPOSE = Path("docker-compose.yml")
DOCKERFILE = Path("Dockerfile")


def test_gate108_scheduler_service_exists():
    text = COMPOSE.read_text()
    assert "container_name: re_os_scheduler_v2" in text


def test_gate108_redis_password_enforcement():
    text = Path("dashboard/state.py").read_text()
    assert "REDIS_PASSWORD" in text
    assert "memory://" in text


def test_gate108_dockerfile_builder_stage():
    text = DOCKERFILE.read_text()
    assert "AS builder" in text


def test_gate108_news_scout_no_ruff_errors():
    result = subprocess.run(
        ["ruff", "check", "scrapers/news_scout.py"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"ruff violations:\n{result.stdout}"


def test_gate108_dead_letter_queue_migration():
    migrations = list(Path("alembic/versions").glob("0064_*.py"))
    assert len(migrations) >= 1
    content = migrations[0].read_text()
    assert "ingest_failed_records" in content
