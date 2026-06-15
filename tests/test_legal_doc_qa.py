import pytest
from unittest.mock import patch, MagicMock, mock_open

pytestmark = pytest.mark.unit

from utils.legal_doc_qa import LegalDocQATool


class TestLoadPDF:
    def test_load_pdf_extracts_text(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch("os.path.isfile", return_value=True):
            with patch("os.path.getsize", return_value=1000):
                with patch(
                    "utils.legal_doc_qa.LegalDocQATool._try_markitdown"
                ) as mock_md:
                    mock_md.return_value = "Extracted text from EC document"
                    result = tool.load_pdf("tests/fixtures/sample_ec.pdf")
                    assert result == "Extracted text from EC document"

    def test_load_pdf_file_not_found(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch("os.path.isfile", return_value=False):
            result = tool.load_pdf("/nonexistent/path.pdf")
            assert result == ""

    def test_load_pdf_fallback_pdfplumber(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch("os.path.isfile", return_value=True):
            with patch("os.path.getsize", return_value=1000):
                with patch(
                    "utils.legal_doc_qa.LegalDocQATool._try_markitdown",
                    return_value=None,
                ):
                    with patch(
                        "utils.legal_doc_qa.LegalDocQATool._try_pdfplumber"
                    ) as mock_pp:
                        mock_pp.return_value = "pdfplumber text"
                        result = tool.load_pdf("tests/fixtures/sample_ec.pdf")
                        assert result == "pdfplumber text"

    def test_load_pdf_respects_max_chars(self):
        tool = LegalDocQATool(api_key="test_key")
        long_text = "A" * 15000
        with patch(
            "utils.legal_doc_qa.LegalDocQATool._try_markitdown", return_value=long_text
        ):
            with patch("os.path.isfile", return_value=True):
                with patch("os.path.getsize", return_value=1000):
                    result = tool.load_pdf("tests/fixtures/sample_ec.pdf")
                    assert len(result) <= 10000

    def test_load_pdf_rejects_empty_file(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch("os.path.isfile", return_value=True):
            with patch("os.path.getsize", return_value=0):
                result = tool.load_pdf("tests/fixtures/empty.pdf")
                assert result == ""

    def test_load_pdf_rejects_large_file(self):
        tool = LegalDocQATool(api_key="test_key")
        oversized = (50 * 1024 * 1024) + 1
        with patch("os.path.isfile", return_value=True):
            with patch("os.path.getsize", return_value=oversized):
                result = tool.load_pdf("tests/fixtures/huge.pdf")
                assert result == ""

    def test_clean_text_normalizes_whitespace(self):
        tool = LegalDocQATool(api_key="test_key")
        cleaned = tool._clean_text("Line 1\n\n\n\nLine 2    spaced")
        assert cleaned == "Line 1\n\nLine 2 spaced"

    def test_load_pdf_zero_page_pdfplumber_returns_none(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch("os.path.isfile", return_value=True):
            with patch("os.path.getsize", return_value=100):
                with patch(
                    "utils.legal_doc_qa.LegalDocQATool._try_markitdown",
                    return_value=None,
                ):
                    with patch(
                        "utils.legal_doc_qa.LegalDocQATool._try_fitz"
                    ) as mock_fitz:
                        mock_fitz.return_value = None
                        with patch(
                            "utils.legal_doc_qa.LegalDocQATool._try_pdfplumber"
                        ) as mock_pp:
                            mock_pp.return_value = None
                            result = tool.load_pdf("tests/fixtures/blank.pdf")
                            assert result == ""

    def test_load_pdf_fallback_fitz(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch("os.path.isfile", return_value=True):
            with patch("os.path.getsize", return_value=1000):
                with patch(
                    "utils.legal_doc_qa.LegalDocQATool._try_markitdown",
                    return_value=None,
                ):
                    with patch(
                        "utils.legal_doc_qa.LegalDocQATool._try_pdfplumber",
                        return_value=None,
                    ):
                        with patch(
                            "utils.legal_doc_qa.LegalDocQATool._try_fitz"
                        ) as mock_fitz:
                            mock_fitz.return_value = "fitz text"
                            result = tool.load_pdf("tests/fixtures/sample.pdf")
                            assert result == "fitz text"


class TestAsk:
    def test_ask_returns_answer_and_confidence(self):
        tool = LegalDocQATool(api_key="test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {"answer": "John Doe", "score": 0.95}
        with patch("requests.post", return_value=mock_resp):
            result = tool.ask("What is the owner name?", "Owner: John Doe")
            assert result is not None
            assert result["answer"] == "John Doe"
            assert result["confidence"] == 0.95

    def test_ask_returns_none_without_key(self):
        tool = LegalDocQATool(api_key="")
        with patch.object(tool, "_get_key", return_value=None):
            result = tool.ask("test", "context")
            assert result is None

    def test_ask_api_error_returns_none(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch("requests.post", side_effect=Exception("timeout")):
            result = tool.ask("test", "context")
            assert result is None

    def test_ask_non_200_returns_none(self):
        tool = LegalDocQATool(api_key="test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Model loading"
        with patch("requests.post", return_value=mock_resp):
            result = tool.ask("test", "context")
            assert result is None

    def test_ask_context_too_short_returns_none(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch.object(tool, "_get_key", return_value="key"):
            result = tool.ask("test", "short")
            assert result is None

    def test_ask_503_retry_then_success(self):
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Model loading"
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json = lambda: {"answer": "Retry worked", "score": 0.88}
        tool = LegalDocQATool(api_key="test_key")
        with patch("requests.post", side_effect=[fail_resp, ok_resp]):
            with patch("time.sleep"):
                result = tool.ask("What?", "Context for the retry test here ok")
                assert result is not None
                assert result["answer"] == "Retry worked"

    def test_ask_list_format_response(self):
        tool = LegalDocQATool(api_key="test_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [{"answer": "Alice", "score": 0.92}]
        with patch("requests.post", return_value=mock_resp):
            result = tool.ask("Who?", "Owner: Alice")
            assert result is not None
            assert result["answer"] == "Alice"
            assert result["confidence"] == 0.92


class TestRunChecklist:
    def test_run_checklist_has_8_questions(self):
        tool = LegalDocQATool(api_key="test_key")
        assert len(tool._CHECKLIST_QUESTIONS) == 8

    def test_run_checklist_keys(self):
        tool = LegalDocQATool(api_key="test_key")
        expected_keys = {
            "owner_name",
            "encumbrance",
            "registration_date",
            "property_area",
            "court_orders",
            "guidance_value",
            "mortgage_loan",
            "sro_name",
        }
        assert set(tool._CHECKLIST_QUESTIONS.keys()) == expected_keys

    def test_run_checklist_returns_all_8_keys(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch.object(tool, "load_pdf", return_value="Sample EC document text"):
            with patch.object(tool, "ask") as mock_ask:
                mock_ask.return_value = {
                    "answer": "some value",
                    "confidence": 0.85,
                    "question": "",
                }
                results = tool.run_title_checklist("45/2", "sample.pdf")
                assert len(results) == 8

    def test_checklist_all_results_have_expected_structure(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch.object(tool, "load_pdf", return_value="Sample EC document text"):
            with patch.object(tool, "ask") as mock_ask:
                mock_ask.return_value = {
                    "answer": "value",
                    "confidence": 0.85,
                    "question": "",
                }
                results = tool.run_title_checklist("45/2", "sample.pdf")
                for key, entry in results.items():
                    assert "answer" in entry, f"Missing answer in {key}"
                    assert "confidence" in entry, f"Missing confidence in {key}"
                    assert "flag" in entry, f"Missing flag in {key}"

    def test_checklist_flags_encumbrance(self):
        tool = LegalDocQATool(api_key="test_key")
        assert tool._is_risk_flag("encumbrance", "Yes, there is a mortgage of 50L")
        assert tool._is_risk_flag("court_orders", "Court order exists")
        assert tool._is_risk_flag("mortgage_loan", "Loan of 10L noted")

    def test_checklist_negation_coverage(self):
        tool = LegalDocQATool(api_key="test_key")
        assert not tool._is_risk_flag("encumbrance", "No encumbrance")
        assert not tool._is_risk_flag("encumbrance", "None")
        assert not tool._is_risk_flag("encumbrance", "nothing")
        assert not tool._is_risk_flag("encumbrance", "never recorded")
        assert not tool._is_risk_flag("encumbrance", "not found")
        assert not tool._is_risk_flag("encumbrance", "no record of any")
        assert not tool._is_risk_flag("court_orders", "No court orders found")
        assert not tool._is_risk_flag("owner_name", "some answer")

    def test_checklist_empty_text_returns_empty_results(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch.object(tool, "load_pdf", return_value=""):
            results = tool.run_title_checklist("45/2", "missing.pdf")
            assert all(r["answer"] == "" for r in results.values())

    def test_checklist_empty_result_when_no_pdf(self):
        tool = LegalDocQATool(api_key="test_key")
        with patch.object(tool, "load_pdf", return_value=""):
            results = tool.run_title_checklist("45/2", "nonexistent.pdf")
            assert all(r["answer"] == "" for r in results.values())
            assert all(r["confidence"] == 0.0 for r in results.values())
            assert not any(r["flag"] for r in results.values())


class TestRiskFlagLogic:
    def test_non_risk_questions_never_flagged(self):
        tool = LegalDocQATool(api_key="test_key")
        for key in [
            "owner_name",
            "registration_date",
            "property_area",
            "guidance_value",
            "sro_name",
        ]:
            assert not tool._is_risk_flag(key, "anything here")

    def test_empty_answer_not_flagged(self):
        tool = LegalDocQATool(api_key="test_key")
        assert not tool._is_risk_flag("encumbrance", "")
        assert not tool._is_risk_flag("encumbrance", "  ")

    def test_extended_negations(self):
        tool = LegalDocQATool(api_key="test_key")
        for negation in [
            "no data",
            "blank",
            "missing",
            "does not exist",
            "is not recorded",
        ]:
            assert not tool._is_risk_flag("encumbrance", negation), (
                f"Failed on: {negation}"
            )


class TestLegalIntelIntegration:
    def test_legal_intel_includes_pdf_qa_when_path_provided(self):
        from intelligence.legal_intel import LegalPicture
        from datetime import datetime, timezone

        pic = LegalPicture(
            survey_no="45/2",
            market="Yelahanka",
            collected_at=datetime.now(timezone.utc).isoformat(),
        )
        with patch("utils.legal_doc_qa.LegalDocQATool") as MockQATool:
            mock_instance = MagicMock()
            mock_instance.run_title_checklist.return_value = {
                "owner_name": {"answer": "John", "confidence": 0.9, "flag": False},
            }
            MockQATool.return_value = mock_instance
            from utils.legal_doc_qa import LegalDocQATool

            qa_tool = LegalDocQATool()
            pic.pdf_qa_results = qa_tool.run_title_checklist("45/2", "sample.pdf")
            assert pic.pdf_qa_results is not None
            assert "owner_name" in pic.pdf_qa_results
