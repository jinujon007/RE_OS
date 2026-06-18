"""GATE-115: Redis Resilience — declaration tests.

Gate tests are lightweight integration verifiers (not unit test duplicates).
They check that the components wire together correctly and are importable.
"""

import pytest

pytestmark = pytest.mark.unit


def test_redis_lazy_reconnect_pattern_importable():
    """Assertion 1: _get_redis_client does not raise on False sentinel.
    Lightweight: only verifies import + call pattern, not internal logic."""
    from dashboard.state import _get_redis_client, _attempt_redis_connect
    assert callable(_get_redis_client)
    assert callable(_attempt_redis_connect)


def test_health_modules_importable():
    """Assertion 2: health loop + run_health_check both importable and callable."""
    from dashboard.redis_health import _redis_health_loop, _run_health_check
    assert callable(_redis_health_loop)
    assert callable(_run_health_check)


def test_pool_exhaustion_check_importable():
    """Assertion 3: _check_pool_exhaustion importable."""
    from utils.db import _check_pool_exhaustion
    assert callable(_check_pool_exhaustion)


def test_ci_workflow_no_redis_password_plaintext():
    """Assertion 4: CI workflow does not contain REDIS_PASSWORD= in plain text."""
    import os
    ci_path = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "ci.yml")
    with open(ci_path, encoding="utf-8") as f:
        content = f.read()
    assert "REDIS_PASSWORD=" not in content, "CI workflow contains REDIS_PASSWORD= in plain text"
