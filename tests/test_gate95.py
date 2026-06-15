"""GATE-95 — Form 17 Parser + Corridor Scorer v1

4 assertions:
(1) Form17Parser importable + _build_records returns ≥10 Sale rows from
    synthetic fixture matching Devanahalli schema (no real PDF required)
(2) kaveri_form17_plugin callable; produces ParsedRecords with entity_type
    'registered_transaction' for sale deed fixtures
(3) corridor_scorer returns ≥3 scored corridors (mocked DB)
(4) Backtest verdict file exists after backtest() call

Integration criterion (live DB only):
    ≥10 Form 17 deed rows in registered_transactions requires J-17 PDF
    (devanahalli_div1_2024_2026.pdf) to be parsed by kaveri_deeds_weekly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


# ── Assertion 1: Form17Parser → ≥10 Sale rows from synthetic fixture ─────────

def _make_sale_rows(n: int = 12) -> list[list[str | None]]:
    """Generate synthetic Form 17 rows that match the real format."""
    rows = []
    for i in range(n):
        doc_no = f"DNH-1-{10000 + i:05d}-2023-24"
        rows.append([
            "Division 1",                           # village
            f"Sale - ₹{(i + 1) * 500000:,}.00",    # deed_type_raw
            f"{100 + i}",                           # survey_no
            "111.42 Sq.Metre",                      # area
            "",                                     # assessment
            f"Seller {i}",                          # executant
            f"Buyer {i}",                           # claimant
            "Devanahalli",                          # sro
            "01-01-2024",                           # exec_date
            f"15-0{(i % 6) + 1}-2024",             # reg_date
            doc_no,                                 # doc_number
            "",                                     # remarks
        ])
    return rows


def test_form17_parser_returns_ten_sale_rows():
    """Assertion 1: Form17Parser._build_records handles ≥10 sale rows."""
    from scrapers.kaveri_form17 import Form17Parser

    parser = Form17Parser()
    rows = _make_sale_rows(12)
    records = parser._build_records(rows, source_ref="devanahalli_div1_2024_2026.pdf")

    sale_records = [r for r in records if r.get("is_sale_deed")]
    assert len(sale_records) >= 10, (
        f"Expected ≥10 Sale rows, got {len(sale_records)}"
    )

    # All 7 required fields non-null
    for r in sale_records[:3]:
        assert r["doc_number"], "doc_number required"
        assert r["registration_date"], "registration_date required"
        assert r["sro"], "sro required"
        assert r["deed_type"] == "Sale", "deed_type must be 'Sale'"
        assert r["consideration_inr"] is not None and r["consideration_inr"] > 0
        assert r["village"], "village required"
        assert r["data_source"] == "kaveri_form17"


def test_form17_parser_zero_validation_errors():
    """All synthetic Sale rows must pass plugin validation."""
    from scrapers.kaveri_form17 import Form17Parser
    from ingest.plugins.kaveri_form17_plugin import KaveriForm17Plugin

    parser = Form17Parser()
    rows = _make_sale_rows(12)
    raw_records = parser._build_records(rows, source_ref="test.pdf")

    plugin = KaveriForm17Plugin()
    errors_found = 0
    parsed_records = []
    for raw in raw_records:
        pr = plugin._build_record(raw, "Devanahalli", cancelled_docs=set())
        if pr is not None:
            result = plugin.validate(pr)
            if not result.valid:
                errors_found += 1
            else:
                parsed_records.append(pr)

    assert errors_found == 0, f"{errors_found} validation errors on synthetic fixtures"
    assert len(parsed_records) >= 10


# ── Assertion 2: plugin produces ParsedRecords ────────────────────────────────

def test_kaveri_form17_plugin_produces_parsed_records():
    """Assertion 2: KaveriForm17Plugin builds ParsedRecords from sale fixture."""
    from ingest.plugins.kaveri_form17_plugin import KaveriForm17Plugin
    from ingest.base import ParsedRecord

    plugin = KaveriForm17Plugin()

    # Inject raw records directly via _build_record
    raw = {
        "doc_number": "DNH-1-99001-2023-24",
        "sro": "Devanahalli",
        "village": "Division 1",
        "deed_type": "Sale",
        "deed_type_raw": "Sale - ₹21,00,000.00",
        "consideration_inr": 2_100_000.0,
        "survey_no_raw": "101",
        "area_raw": "111.42 Sq.Metre",
        "extent_sqft": 1199.5,
        "executant": "John Doe",
        "claimant": "Jane Smith",
        "execution_date": "2024-01-01",
        "registration_date": "2024-01-15",
        "remarks": "",
        "is_sale_deed": True,
        "cancels_doc_number": None,
        "psf": 1750.5,
        "data_source": "kaveri_form17",
        "source_ref": "devanahalli_div1_2024_2026.pdf",
        "extraction_confidence": "high",
    }
    pr = plugin._build_record(raw, "Devanahalli", cancelled_docs=set())
    assert pr is not None
    assert isinstance(pr, ParsedRecord)
    assert pr.entity_type == "registered_transaction"
    assert pr.data["doc_no"] == "DNH-1-99001-2023-24"
    assert pr.data["is_sale_deed"] is True
    assert pr.data["data_source"] == "kaveri_form17"
    # source_id truncated to ≤100 chars
    assert len(pr.source_id) <= 100


# ── Assertion 3: corridor_scorer returns ≥3 corridors ────────────────────────

def test_corridor_scorer_returns_three_corridors():
    """Assertion 3: CorridorScorer.score_all() returns ≥3 scored corridors."""
    from utils.corridor_scorer import CorridorScorer

    engine = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone = MagicMock(return_value=(0,))
    conn.execute = MagicMock(return_value=cursor)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    engine.connect = MagicMock(return_value=conn)

    scorer = CorridorScorer(engine=engine)
    scores = scorer.score_all()

    assert len(scores) >= 3, f"Expected ≥3 corridors, got {len(scores)}"
    for s in scores:
        assert 0.0 <= s.composite <= 10.0
        assert s.corridor_id
        assert s.corridor_name


# ── Assertion 4: backtest verdict file exists ─────────────────────────────────

def test_backtest_verdict_file_written():
    """Assertion 4: backtest() writes verdict markdown file."""
    from utils.corridor_scorer import CorridorScorer

    engine = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone = MagicMock(return_value=(None,))
    conn.execute = MagicMock(return_value=cursor)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    engine.connect = MagicMock(return_value=conn)

    scorer = CorridorScorer(engine=engine)

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "corridor_scorer_backtest.md"
        result = scorer.backtest(output_path=output)

        assert output.exists(), "Backtest report file not created"
        content = output.read_text()
        assert "Corridor Scorer" in content
        assert "Verdict" in content
        assert result["verdict"] in ("PASS", "FAIL", "INSUFFICIENT_DATA")
        # INSUFFICIENT_DATA expected here since DB has no real data
        assert result["verdict"] == "INSUFFICIENT_DATA"
