"""T-1288 — k6 CI stage recalibration."""
import pytest
from pathlib import Path
pytestmark = pytest.mark.unit

def test_k6_script_uses_ci_stages():
    script = Path("tests/load/k6_baseline.js")
    assert script.exists()
    content = script.read_text()
    assert "target: 20" in content, "k6 script should use CI baseline of 20 VUs"
    assert "target: 50" not in content, "CI script must not use aggressive 50 VU stage"
    assert "p(95)<500" in content, "CI threshold p95 should be 500ms"
    assert "rate<0.01" in content, "CI threshold for failure rate should be <1%"
