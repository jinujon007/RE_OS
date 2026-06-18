"""Tests for Redis password enforcement (T-1229 / GATE-108)."""

import os
import pytest


def test_redis_password_enforcement_logic_exists():
    """dashboard/state.py must have REDIS_PASSWORD enforcement check."""
    text = __import__("dashboard.state", fromlist=["_REDIS_PASSWORD"]).__file__
    source = open(text.replace(".pyc", ".py")).read() if text.endswith("c") else open(text).read()
    assert "REDIS_PASSWORD" in source


def test_redis_compose_requires_password():
    """docker-compose.yml redis-server command must NOT have :-
    fallback (requires non-empty password)."""
    from pathlib import Path
    text = Path("docker-compose.yml").read_text()
    redis_section = text.split("container_name: re_os_redis")[1].split("  # ──")[0]
    assert "requirepass" in redis_section
    assert "${REDIS_PASSWORD:-}" not in redis_section  # no empty fallback


def test_redis_memory_url_bypasses_password_check():
    """REDIS_URL=memory:// should not trigger password enforcement."""
    env_backup = {}
    for key in ("REDIS_URL", "REDIS_PASSWORD"):
        env_backup[key] = os.environ.pop(key, None)
    os.environ["REDIS_URL"] = "memory://"
    os.environ["REDIS_PASSWORD"] = ""
    try:
        from importlib import reload
        import dashboard.state
        reload(dashboard.state)
    except RuntimeError:
        pytest.fail("memory:// should bypass password enforcement")
    finally:
        for key, val in env_backup.items():
            if val is not None:
                os.environ[key] = val
            elif key in os.environ:
                del os.environ[key]


def test_docker_compose_redis_has_healthcheck():
    from pathlib import Path
    text = Path("docker-compose.yml").read_text()
    redis_section = text.split("container_name: re_os_redis")[1].split("  # ──")[0]
    assert "healthcheck:" in redis_section
    assert "redis-cli" in redis_section
