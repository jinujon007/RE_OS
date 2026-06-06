"""
RE_OS — RERA Field Extractor (T-965)
Extracts structured fields from RERA project text.
Primary: Ollama rera-qwen model (after fine-tune). Falls back to regex.

Supports two input formats:
  - Structured key:value text (Project: ..., Developer: ...)
  - HTML table rows (<tr><td>...</td></tr>) from RERA Karnataka portal

Risk mitigations:
  - Ollama check has 300s TTL — detects model start/stop without restart
  - 3 retries with exponential backoff on Ollama API calls
  - Regex handles both text and HTML formats
  - SSL context configured for corporate proxy compatibility
"""
import json
import os
import re
import ssl
import time
import urllib.request
from typing import Optional
from loguru import logger

__all__ = ["RERAExtractor"]

_OUTPUT_SCHEMA = frozenset({
    "project_name", "developer_name", "survey_no", "units",
    "launch_date", "completion_date", "status", "market",
})

_DEFAULT_RESULT = {
    "project_name": "",
    "developer_name": "",
    "survey_no": "",
    "units": 0,
    "launch_date": "",
    "completion_date": "",
    "status": "",
    "market": "",
}

# How long before re-checking if Ollama rera-qwen model is available (seconds)
_OLLAMA_CACHE_TTL = int(os.environ.get("RERA_OLLAMA_CACHE_TTL", "300"))

# Max retries for Ollama API calls with exponential backoff
_OLLAMA_MAX_RETRIES = 3
_OLLAMA_BASE_TIMEOUT = 30

# Known RERA portal column patterns for HTML extraction
_HTML_COLUMN_PATTERNS = [
    (2, "project_name"),     # Column 2: REGISTRATION NO — skip, use column 5
    (4, "developer_name"),   # Column 4: PROMOTER NAME
    (5, "project_name"),     # Column 5: PROJECT NAME
    (6, "status"),           # Column 6: STATUS
    (7, "market"),           # Column 7: DISTRICT
    (8, "market_fallback"),  # Column 8: TALUK (fallback if no market)
    (9, "project_type"),     # Column 9: PROJECT TYPE — skip
    (10, "launch_date"),     # Column 10: APPROVED ON
    (11, "completion_date"), # Column 11: PROPOSED COMPLETION DATE
]


def _create_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if os.environ.get("RERA_SSL_VERIFY", "1").lower() in ("0", "false", "no"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class RERAExtractor:
    def __init__(self, ollama_base_url: str = "http://localhost:11434"):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self._model_available: Optional[bool] = None
        self._model_last_check: float = 0.0
        self._ssl_ctx = _create_ssl_context()

    def _check_ollama_model(self) -> bool:
        now = time.time()
        if self._model_available is not None and (now - self._model_last_check) < _OLLAMA_CACHE_TTL:
            return self._model_available
        try:
            req = urllib.request.Request(f"{self.ollama_base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3, context=self._ssl_ctx) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                self._model_available = any("rera-qwen" in m for m in models)
                logger.info(
                    "[RERAExtractor] Ollama rera-qwen model %s",
                    "found" if self._model_available else "not found",
                )
        except Exception as exc:
            logger.debug(f"[RERAExtractor] Ollama check failed: {exc}")
            self._model_available = False
        self._model_last_check = now
        return self._model_available

    def _extract_via_ollama(self, raw_text: str) -> Optional[dict]:
        prompt = (
            "Extract RERA fields as JSON from this text. "
            "Return ONLY valid JSON with these keys: "
            "project_name, developer_name, survey_no, units, "
            "launch_date, completion_date, status, market. "
            "No explanation. No markdown.\n\n"
            f"Text:\n{raw_text[:2000]}"
        )
        body = json.dumps({
            "model": "rera-qwen",
            "prompt": prompt,
            "stream": False,
            "temperature": 0.1,
        }).encode()

        last_error = None
        for attempt in range(_OLLAMA_MAX_RETRIES):
            try:
                timeout = _OLLAMA_BASE_TIMEOUT * (attempt + 1)
                req = urllib.request.Request(
                    f"{self.ollama_base_url}/api/generate",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout, context=self._ssl_ctx) as resp:
                    result = json.loads(resp.read().decode())
                    raw = result.get("response", "")
                    parsed = self._parse_json_from_text(raw)
                    if parsed and self._validate_schema(parsed):
                        return parsed
                    logger.warning(f"[RERAExtractor] Ollama returned invalid JSON: {raw[:200]}")
                break
            except Exception as exc:
                last_error = exc
                if attempt < _OLLAMA_MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.debug(f"[RERAExtractor] Ollama attempt {attempt+1} failed, retry in {wait}s: {exc}")
                    time.sleep(wait)
                else:
                    logger.debug(f"[RERAExtractor] Ollama extraction failed after {_OLLAMA_MAX_RETRIES} retries: {last_error}")
        return None

    def _parse_json_from_text(self, text: str) -> Optional[dict]:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        return None

    def _validate_schema(self, data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        return bool(_OUTPUT_SCHEMA.intersection(data.keys()))

    @staticmethod
    def _clean_cell(text: str) -> str:
        return text.strip().rstrip(",").strip()

    def _extract_fields_from_html(self, raw_text: str) -> dict:
        """Extract fields from RERA portal HTML table rows (<tr><td>...)."""
        result = {}
        soup = None
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_text, "lxml")
        except ImportError:
            pass

        if soup is not None:
            rows = soup.select("tr")
            for row in rows:
                tds = row.select("td")
                cells = [self._clean_cell(td.get_text(strip=True)) for td in tds]
                if len(cells) < 6:
                    continue
                if cells[0] in ("S.NO", "") or cells[1] in ("ACKNOWLEDGEMENT NO", ""):
                    continue
                result["project_name"] = cells[5] if len(cells) > 5 else result.get("project_name", "")
                result["developer_name"] = cells[4] if len(cells) > 4 else result.get("developer_name", "")
                result["status"] = cells[6] if len(cells) > 6 else result.get("status", "")
                if len(cells) > 10:
                    result["launch_date"] = cells[10]
                if len(cells) > 11:
                    result["completion_date"] = cells[11]
                if not result.get("market") and len(cells) > 7:
                    result["market"] = cells[7]
                rera_match = re.search(r"[A-Z0-9/.-]+", cells[2] if len(cells) > 2 else "")
                if rera_match:
                    result["survey_no"] = rera_match.group(0)
                if not result.get("survey_no") and len(cells) > 1:
                    ack_match = re.search(r"[A-Z0-9/.-]+", cells[1])
                    if ack_match:
                        result["survey_no"] = ack_match.group(0)
        return result

    def _extract_via_regex(self, raw_text: str) -> dict:
        result = dict(_DEFAULT_RESULT)

        # Try HTML extraction first
        html_fields = self._extract_fields_from_html(raw_text)
        if html_fields.get("project_name") or html_fields.get("developer_name"):
            result.update(html_fields)
            if result["units"] == 0:
                units_match = re.search(r"(\d+)\s*(?:units|unit|flats)", raw_text, re.IGNORECASE)
                if units_match:
                    try:
                        result["units"] = int(units_match.group(1))
                    except (ValueError, TypeError):
                        pass
            return result

        # Structured key:value text patterns (fallback)
        patterns = {
            "project_name": [
                r"(?:Project|Project Name)[:\s]+([^\n]+)",
                r"project_name[:\"]+\s*\"?([^\",\n]+)",
            ],
            "developer_name": [
                r"(?:Developer|Promoter|Developer Name)[:\s]+([^\n]+)",
                r"developer(?:er|_name)[:\"]+\s*\"?([^\",\n]+)",
            ],
            "survey_no": [
                r"(?:RERA (?:No|Number|Registration|ID)|RERA/|Survey No)[:\s]+([^\n]+)",
                r"rera(?:_id|_number|_no)[:\"]+\s*\"?([^\",\n]+)",
                r"survey_no[:\"]+\s*\"?([^\",\n]+)",
            ],
            "launch_date": [
                r"(?:Launch Date|Launch|Approved On)[:\s]+([^\n]+)",
                r"launch_date[:\"]+\s*\"?([^\",\n]+)",
            ],
            "completion_date": [
                r"(?:Completion Date|Possession Date|Proposed Completion)[:\s]+([^\n]+)",
                r"completion_date[:\"]+\s*\"?([^\",\n]+)",
            ],
            "status": [
                r"(?:Status|Project Status)[:\s]+([^\n]+)",
                r"status[:\"]+\s*\"?([^\",\n]+)",
            ],
            "market": [
                r"(?:Market|District|Taluk)[:\s]+([^\n]+)",
                r"market[:\"]+\s*\"?([^\",\n]+)",
            ],
        }

        for field, field_patterns in patterns.items():
            for pat in field_patterns:
                m = re.search(pat, raw_text, re.IGNORECASE)
                if m:
                    val = m.group(1).strip().strip('"').strip("'")
                    if val:
                        result[field] = val
                        break

        units_match = re.search(
            r"(?:Total Units|Units)[:\s]+(\d+)",
            raw_text,
            re.IGNORECASE,
        )
        if units_match:
            try:
                result["units"] = int(units_match.group(1))
            except (ValueError, TypeError):
                pass

        return result

    def extract(self, raw_text: str) -> dict:
        if not raw_text or not raw_text.strip():
            return dict(_DEFAULT_RESULT)

        if self._check_ollama_model():
            result = self._extract_via_ollama(raw_text)
            if result:
                return self._coerce_types(result)

        return self._coerce_types(self._extract_via_regex(raw_text))

    @staticmethod
    def _coerce_types(data: dict) -> dict:
        raw_units = data.get("units")
        if raw_units is not None:
            try:
                data["units"] = int(raw_units)
            except (ValueError, TypeError):
                data["units"] = 0
        else:
            data["units"] = 0
        for str_field in ("project_name", "developer_name", "survey_no", "launch_date", "completion_date", "status", "market"):
            if data.get(str_field) is not None and not isinstance(data[str_field], str):
                data[str_field] = str(data[str_field])
        return data
