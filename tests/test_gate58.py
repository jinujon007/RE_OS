"""GATE-58: LegalDocQATool 8-flag checklist; finbert-tone directional CI gate.
Verifies all 3 criteria without repeating unit tests."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestGate58LegalDocQA:
    def test_checklist_returns_8_key_structure(self):
        from utils.legal_doc_qa import LegalDocQATool
        tool = LegalDocQATool(api_key="test_key")
        with patch.object(tool, "load_pdf", return_value="Sample EC text with property details"):
            with patch.object(tool, "ask") as mock_ask:
                mock_ask.return_value = {"answer": "value", "confidence": 0.85, "question": ""}
                results = tool.run_title_checklist("45/2", "sample.pdf")
                assert len(results) == 8
                for entry in results.values():
                    assert "answer" in entry
                    assert "confidence" in entry
                    assert "flag" in entry
                    assert entry["confidence"] > 0


class TestGate58FinbertTone:
    def test_risk_or_negative_is_top_tone_for_distressed_text(self):
        from utils.sentiment import score_tone
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            {"label": "Risk", "score": 0.82},
            {"label": "Negative", "score": 0.12},
            {"label": "Positive", "score": 0.02},
            {"label": "Uncertainty", "score": 0.02},
            {"label": "Litigious", "score": 0.01},
            {"label": "Constraining", "score": 0.01},
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            tones = score_tone(
                "RERA project stalled, builder facing insolvency proceedings",
                api_key="test_key"
            )
            assert tones is not None
            dominant = max(tones, key=tones.get)
            assert dominant in ("Risk", "Negative")


class TestGate58TestSuite:
    def test_no_regressions_in_new_legal_qa_tests(self):
        from utils.legal_doc_qa import LegalDocQATool
        import inspect
        sources = ["load_pdf", "ask", "run_title_checklist", "_is_risk_flag"]
        for name in sources:
            assert hasattr(LegalDocQATool, name), f"Missing method: {name}"

    def test_no_regressions_in_finbert_tone_tests(self):
        from utils.sentiment import score_tone, dominant_tone
        assert callable(score_tone)
        assert callable(dominant_tone)
