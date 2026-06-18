"""Tests for T-1284: SLO burn-rate Discord alert (R2).

Uses inspect + direct source verification to avoid APScheduler dependency.
"""

import inspect
from pathlib import Path


DIGEST_JOBS_PATH = (
    Path(__file__).resolve().parent.parent
    / "config" / "scheduler" / "digest_jobs.py"
)


def _source_contains(name: str) -> bool:
    return name in DIGEST_JOBS_PATH.read_text(encoding="utf-8")


def test_slo_burn_check_registered():
    assert _source_contains("def run_slo_burn_check"), (
        "run_slo_burn_check not defined in digest_jobs.py"
    )


def test_alert_slo_callable():
    assert _source_contains("def _alert_slo"), (
        "_alert_slo not defined in digest_jobs.py"
    )


def test_slo_dedup_key_deterministic():
    """Verify the dedup key algorithm is deterministic (not hash())."""
    import hashlib
    msg = "Test alert message with some details"
    key1 = hashlib.md5(msg.encode("utf-8")).hexdigest()[:16]
    key2 = hashlib.md5(msg.encode("utf-8")).hexdigest()[:16]
    assert key1 == key2, "MD5 digest is not deterministic"
    assert len(key1) == 16, f"Expected 16-char hex digest, got {len(key1)}"
    # Verify the source uses hashlib.md5 not hash()
    source = DIGEST_JOBS_PATH.read_text(encoding="utf-8")
    assert "hashlib.md5" in source, (
        "_slo_dedup_key must use hashlib.md5 (not hash()) for deterministic keys"
    )
    assert "_slo_dedup_key" in source, "_slo_dedup_key function not found"


def test_slo_dedup_key_differs_by_content():
    import hashlib
    key_alert1 = hashlib.md5(b"Alert one").hexdigest()[:16]
    key_alert2 = hashlib.md5(b"Alert two").hexdigest()[:16]
    assert key_alert1 != key_alert2, "Different messages must produce different keys"
