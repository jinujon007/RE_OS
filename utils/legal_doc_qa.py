"""
RE_OS — Legal Document QA Tool (Sprint 34 Deferred)
PDF question-answering for encumbrance certificates and title deeds using
deepset/roberta-base-squad2 via HF Inference API.

Usage:
    tool = LegalDocQATool()
    text = tool.load_pdf("ec_45_2.pdf")
    result = tool.ask("What is the property area?", text)
    checklist = tool.run_title_checklist("45/2", "ec_45_2.pdf")
"""

import os
from loguru import logger

__all__ = ["LegalDocQATool"]

_SENTINEL = object()
_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
_HF_RETRY_ATTEMPTS = 3
_HF_RETRY_BASE_DELAY = 2


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter (±25%) to prevent thundering herd."""
    import random

    base = _HF_RETRY_BASE_DELAY * (2**attempt)
    jitter = base * random.uniform(-0.25, 0.25)
    return round(base + jitter, 2)


class LegalDocQATool:
    _HF_BASE = "https://router.huggingface.co/hf-inference/models/"
    _QA_MODEL = "deepset/roberta-base-squad2"
    _TIMEOUT = 20
    _MAX_CHARS = 10000

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key

    def _get_key(self) -> str | None:
        key = self._api_key or os.environ.get("HF_API_KEY", "")
        if not key:
            logger.warning("[LegalDocQA] No HF_API_KEY available — QA calls will fail")
        return key if key else None

    def load_pdf(self, path: str) -> str:
        if not os.path.isfile(path):
            logger.warning("[LegalDocQA] PDF not found: {}", path)
            return ""
        file_size = os.path.getsize(path)
        if file_size > _MAX_FILE_SIZE_BYTES:
            logger.warning(
                "[LegalDocQA] File too large ({} MB), refusing: {}",
                round(file_size / (1024 * 1024), 1),
                path,
            )
            return ""
        if file_size == 0:
            logger.warning("[LegalDocQA] Empty file: {}", path)
            return ""
        text = self._try_markitdown(path)
        if text:
            return text[: self._MAX_CHARS]
        text = self._try_pdfplumber(path)
        if text:
            return text[: self._MAX_CHARS]
        text = self._try_fitz(path)
        if text:
            return text[: self._MAX_CHARS]
        logger.warning("[LegalDocQA] All PDF extractors failed for: {}", path)
        return ""

    def _try_markitdown(self, path: str) -> str | None:
        try:
            from markitdown import MarkItDown

            md = MarkItDown()
            result = md.convert(path)
            text = (
                result.text_content if hasattr(result, "text_content") else str(result)
            )
            return self._clean_text(text) if text else None
        except Exception as exc:
            logger.debug("[LegalDocQA] markitdown failed: {}", exc)
            return None

    def _try_pdfplumber(self, path: str) -> str | None:
        try:
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            if not pages:
                return None
            text = "\n".join(pages)
            return self._clean_text(text) if text.strip() else None
        except Exception as exc:
            logger.debug("[LegalDocQA] pdfplumber failed: {}", exc)
            return None

    def _try_fitz(self, path: str) -> str | None:
        try:
            import fitz

            doc = fitz.open(path)
            pages = [page.get_text() for page in doc]
            doc.close()
            if not pages:
                return None
            text = "\n".join(pages)
            return self._clean_text(text) if text.strip() else None
        except Exception as exc:
            logger.debug("[LegalDocQA] PyMuPDF (fitz) failed: {}", exc)
            return None

    def _clean_text(self, text: str) -> str:
        import re

        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        return text.strip()

    def ask(
        self, question: str, context: str, api_key: str | object = _SENTINEL
    ) -> dict | None:
        key = self._get_key() if api_key is _SENTINEL else api_key
        if not key or not context or not question:
            return None
        if len(context) < 10:
            logger.debug(
                "[LegalDocQA] Context too short ({}/10 chars) for QA", len(context)
            )
            return None
        import requests as _requests
        import time as _time

        for attempt in range(_HF_RETRY_ATTEMPTS):
            try:
                resp = _requests.post(
                    f"{self._HF_BASE}{self._QA_MODEL}",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "inputs": {
                            "question": question[:256],
                            "context": context[:4000],
                        }
                    },
                    timeout=self._TIMEOUT,
                )
                if resp.status_code in (503, 429):
                    delay = _retry_delay(attempt)
                    logger.debug(
                        "[LegalDocQA] HF API {} (attempt {}/{}), retrying in {:.1f}s",
                        resp.status_code,
                        attempt + 1,
                        _HF_RETRY_ATTEMPTS,
                        delay,
                    )
                    _time.sleep(delay)
                    continue
                if resp.status_code != 200:
                    logger.warning(
                        "[LegalDocQA] HF API {}: {}", resp.status_code, resp.text[:100]
                    )
                    return None
                data = resp.json()
                answer = (
                    data.get("answer", "")
                    if isinstance(data, dict)
                    else (
                        data[0].get("answer", "")
                        if isinstance(data, list) and data
                        else ""
                    )
                )
                confidence = (
                    data.get("score", 0.0)
                    if isinstance(data, dict)
                    else (
                        data[0].get("score", 0.0)
                        if isinstance(data, list) and data
                        else 0.0
                    )
                )
                return {
                    "answer": answer,
                    "confidence": round(confidence, 4),
                    "question": question,
                }
            except Exception as exc:
                if attempt == _HF_RETRY_ATTEMPTS - 1:
                    logger.debug(
                        "[LegalDocQA] ask error after {} attempts: {}",
                        _HF_RETRY_ATTEMPTS,
                        exc,
                    )
                    return None
                _time.sleep(_retry_delay(attempt))
                continue
        return None

    def run_title_checklist(self, survey_no: str, pdf_path: str) -> dict:
        text = self.load_pdf(pdf_path)
        if not text:
            logger.warning(
                "[LegalDocQA] No text extracted from {} — empty checklist returned",
                pdf_path,
            )
            return {
                q: {"answer": "", "confidence": 0.0, "flag": False}
                for q in self._CHECKLIST_QUESTIONS
            }

        logger.info(
            "[LegalDocQA] Running {} title checklist questions on {} ({} chars)",
            len(self._CHECKLIST_QUESTIONS),
            pdf_path,
            len(text),
        )

        results = {}
        for i, (q_key, q_text) in enumerate(self._CHECKLIST_QUESTIONS.items(), 1):
            logger.debug(
                "[LegalDocQA] [{}/{}] Asking: {}",
                i,
                len(self._CHECKLIST_QUESTIONS),
                q_text,
            )
            answer_data = self.ask(q_text, text)
            if answer_data and answer_data.get("answer"):
                results[q_key] = {
                    "answer": answer_data["answer"],
                    "confidence": answer_data["confidence"],
                    "flag": self._is_risk_flag(q_key, answer_data["answer"]),
                }
            else:
                results[q_key] = {"answer": "", "confidence": 0.0, "flag": False}

        flagged = sum(1 for r in results.values() if r["flag"])
        logger.info(
            "[LegalDocQA] Checklist complete: {}/{} questions flagged",
            flagged,
            len(results),
        )
        return results

    def _is_risk_flag(self, question_key: str, answer: str) -> bool:
        risk_questions = {"encumbrance", "court_orders", "mortgage_loan"}
        if question_key not in risk_questions:
            return False
        answer_stripped = answer.strip().lower()
        if not answer_stripped:
            return False
        negations = {
            "no",
            "none",
            "nil",
            "not",
            "n/a",
            "na",
            "null",
            "0",
            "nothing",
            "never",
            "no record",
            "not found",
            "no entry",
            "no data",
            "blank",
            "missing",
            "does not",
            "is not",
        }
        return not any(answer_stripped.startswith(n) for n in negations)

    _CHECKLIST_QUESTIONS = {
        "owner_name": "What is the property owner name?",
        "encumbrance": "Is there any encumbrance noted?",
        "registration_date": "What is the registration date?",
        "property_area": "What is the property area in square feet?",
        "court_orders": "Are there any court orders or injunctions?",
        "guidance_value": "What is the market value or guidance value?",
        "mortgage_loan": "Is there a mortgage or loan noted?",
        "sro_name": "What is the SRO name?",
    }
