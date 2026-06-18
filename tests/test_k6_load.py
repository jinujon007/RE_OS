"""T-1249: k6 load test script tests."""
import os
import pytest

pytestmark = pytest.mark.unit


def test_k6_load_script_exists():
    """tests/load/k6_baseline.js exists and has valid k6 options."""
    script_path = os.path.join(os.path.dirname(__file__), "load", "k6_baseline.js")
    assert os.path.exists(script_path), f"k6 baseline script not found at {script_path}"

    with open(script_path) as f:
        content = f.read()

    assert "stages" in content, "Expected staged ramp-up (not flat vus)"
    assert "http_req_failed" in content, "Expected http_req_failed threshold"
    assert "http_req_duration" in content, "Expected http_req_duration threshold"
    assert "health/live" in content, "Expected health/live endpoint"
    assert "thresholds" in content, "Expected thresholds block"
