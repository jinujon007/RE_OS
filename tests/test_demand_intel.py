"""DemandIntel tests — str + T-1235 NRI signal."""

import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


def test_demand_signals_str_with_none_fields():
    from intelligence.demand_intel import DemandSignals

    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-05T00:00:00")
    result = str(ds)
    assert "DemandSignals" in result
    assert "UNKNOWN" in result or "0.0" in result


# ── T-1235: NRI signal uses registered_transactions buyer_type ────────────────


def _make_mi(slug="yelahanka", name="Yelahanka"):
    return {"slug": slug, "name": name, "id": 1}


def _conn_with_results(values):
    """Return a mock connection whose execute().scalar() returns values in order."""
    conn = MagicMock()
    call_count = [0]

    def execute_side(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        val = values[min(idx, len(values) - 1)]
        r = MagicMock()
        r.scalar.return_value = val
        return r

    conn.execute.side_effect = execute_side
    return conn


def test_nri_signal_uses_deed_buyer_type_when_available():
    from intelligence.demand_intel import DemandIntel, DemandSignals

    di = DemandIntel()
    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-17")
    mi = _make_mi()

    conn = _conn_with_results([3, 100])

    di._compute_nri_demand_score(conn, ds, mi)

    assert ds.nri_score is not None and ds.nri_score > 0
    assert any("nri buyer_type" in s for s in ds.signals), (
        f"Expected signal referencing deed buyer_type, got {ds.signals}"
    )


def test_nri_signal_fallback_on_insufficient_deeds():
    from intelligence.demand_intel import DemandIntel, DemandSignals

    di = DemandIntel()
    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-17")
    mi = _make_mi()

    conn = _conn_with_results([0, 3, 4])
    # 0 deed_count, 3 rows (<5 → fallback), 4 news articles

    di._compute_nri_demand_score(conn, ds, mi)

    assert any("news_fallback" in s for s in ds.signals), (
        f"Expected fallback signal, got {ds.signals}"
    )


def test_nri_low_confidence_label_on_fallback():
    from intelligence.demand_intel import DemandIntel, DemandSignals

    di = DemandIntel()
    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-17")
    mi = _make_mi()

    conn = _conn_with_results([0, 3, 2])

    di._compute_nri_demand_score(conn, ds, mi)

    assert any("LOW_CONFIDENCE" in s for s in ds.signals), (
        f"Expected [LOW_CONFIDENCE] label, got {ds.signals}"
    )
