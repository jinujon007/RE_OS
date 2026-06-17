"""BhoomiRTCParser — parse Bhoomi portal RTC HTML into ownership chain (GATE-99, T-1186).

Takes the HTML string returned by BhoomiScraper.fetch(survey_no, market) and
extracts the ownership chain: khata number, current owner, previous owner,
transfer date, area, encumbrance detail, and government acquisition notice.

Tolerant: returns partial dict on malformed HTML, never raises.
Returns a parser_completeness_score (0.0–1.0) so callers can detect degradation.
"""

import re
from loguru import logger

_GOVT_ACQUISITION_PATTERNS = re.compile(
    r"(government|bda|kiadb|bmrcl|bbmp|acquisition|notified|"
    r"ಕರ್ನಾಟಕ\s*ಸರ್ಕಾರ|ಸ್ವಾಧೀನ|ಸೂಚನೆ)",
    re.IGNORECASE,
)

_KHATA_PATTERN = re.compile(
    r"Khata\s*(?:No|Number|#|ಸಂಖ್ಯೆ)[:\s]*([\w/\-]+)",
    re.IGNORECASE,
)

_DATE_DMY = re.compile(r"(\d{2})[/-](\d{2})[/-](\d{4})")
_DATE_YMD = re.compile(r"(\d{4})[/-](\d{2})[/-](\d{2})")

_AREA_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(Guntas|guntas|Acres|acres|Acre|acre|Cents|cents|"
    r"sq\.?\s*m|Sq\.?\s*Mt|ಗುಂಟೆ|ಎಕರೆ|ಸೆಂಟ్)",
)

_AREA_FALLBACK = re.compile(r"Area[:\s]*(\d+(?:\.\d+)?)", re.IGNORECASE)

_NON_ASCII_PATTERN = re.compile(r"[^\x20-\x7E]")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def _find_table_cell(html: str, header_text: str) -> str | None:
    pattern = re.compile(
        r"<th[^>]*>\s*" + re.escape(header_text) + r"\s*</th>\s*<td[^>]*>(.*?)</td>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    if match:
        val = _strip_html(match.group(1)).strip()
        return val if val else None
    return None


def _extract_table_section(html: str, header_text: str) -> str | None:
    pos = html.find(header_text)
    if pos == -1:
        return None
    table_start = html.rfind("<table", 0, pos)
    if table_start == -1:
        table_start = pos
    table_end = html.find("</table>", pos)
    if table_end == -1:
        return None
    return html[table_start : table_end + 8]


def _normalize_date(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    m = _DATE_YMD.match(raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_DMY.match(raw)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return raw


def _parse_govt_acquisition(html: str, parsed: dict) -> None:
    text_content = _strip_html(html)
    matches = _GOVT_ACQUISITION_PATTERNS.findall(text_content)
    if matches:
        parsed["govt_acquisition_notice"] = True
        parsed["govt_acquisition_detail"] = " | ".join(set(m.strip() for m in matches if m.strip()))
    else:
        parsed["govt_acquisition_notice"] = False
        parsed["govt_acquisition_detail"] = None


def _parse_encumbrance(html: str, parsed: dict) -> None:
    enc_table = _extract_table_section(html, "Encumbrance")
    if not enc_table:
        enc_table = _extract_table_section(html, "ENCUMBRANCE")
    if not enc_table:
        enc_table = _extract_table_section(html, "\u0c2d\u0c3e\u0cb0")
    if not enc_table:
        parsed["encumbrance_flag"] = False
        parsed["encumbrance_detail"] = None
        return
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", enc_table, re.IGNORECASE | re.DOTALL)
    data_rows = [r for r in rows if "<th" not in r and len(_strip_html(r).strip()) > 5]
    if not data_rows:
        data_rows = [r for r in rows if len(_strip_html(r).strip()) > 10]
    if not data_rows:
        data_rows = rows[1:] if len(rows) > 1 else []
    if data_rows:
        parsed["encumbrance_flag"] = True
        details = []
        for r in data_rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.IGNORECASE | re.DOTALL)
            cell_texts = [_strip_html(c).strip() for c in cells if _strip_html(c).strip()]
            details.append(" | ".join(cell_texts))
        parsed["encumbrance_detail"] = " || ".join(details)
    else:
        parsed["encumbrance_flag"] = False
        parsed["encumbrance_detail"] = None


def _parse_area(html: str, parsed: dict) -> None:
    total_acres = 0.0
    found = False
    for m in _AREA_PATTERN.finditer(html):
        try:
            val = float(m.group(1))
            unit_text = m.group(2).lower()
        except (ValueError, TypeError):
            continue
        found = True
        if "cent" in unit_text or "\u0cb8\u0cc6\u0c82\u0c9f\u0ccd" in unit_text:
            total_acres += val / 100.0
        elif "gunta" in unit_text or "\u0c97\u0cc1\u0c82\u0c9f\u0cc6" in unit_text:
            total_acres += val / 40.0
        elif "acre" in unit_text or "\u0c8e\u0c95\u0cb0\u0cc6" in unit_text:
            total_acres += val
        elif "sq" in unit_text:
            total_acres += val / 43560.0
    if found:
        parsed["area_acres"] = round(total_acres, 6)
        return
    fallback = _AREA_FALLBACK.search(html)
    if fallback:
        try:
            parsed["area_acres"] = round(float(fallback.group(1)), 6)
        except (ValueError, TypeError):
            pass


def _parse_previous_owner(html: str, parsed: dict) -> None:
    prev_section = _extract_table_section(html, "Previous")
    if not prev_section:
        prev_section = _extract_table_section(html, "Prior")
    if not prev_section:
        prev_section = _extract_table_section(html, "Earlier")
    if not prev_section:
        prev_section = _extract_table_section(html, "\u0cb9\u0cbf\u0c82\u0ca6\u0cbf\u0ca8")
    if prev_section:
        prev_match = re.search(
            r"(?:Previous|Prior|Earlier|\u0cb9\u0cbf\u0c82\u0ca6\u0cbf\u0ca8)\s*"
            r"(?:Holder|Owner|\u0cb9\u0cc6\u0cb8\u0cb0\u0cc1)[:\s]*(.*?)(?:<|$)",
            prev_section,
            re.IGNORECASE | re.DOTALL,
        )
        if prev_match:
            parsed["previous_owner"] = _strip_html(prev_match.group(1)).strip() or None
            if parsed["previous_owner"] == parsed.get("owner_name"):
                parsed["previous_owner"] = None
            return

    if parsed.get("owner_name"):
        holder_table = _extract_table_section(html, "Holder")
        if holder_table:
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", holder_table, re.IGNORECASE | re.DOTALL)
            name_cells = []
            for row in rows:
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.IGNORECASE | re.DOTALL)
                for c in cells:
                    cleaned = _strip_html(c).strip()
                    if len(cleaned) > 5 and not re.match(r"^[\d\s./\-]+$", cleaned):
                        name_cells.append(cleaned)
            if len(name_cells) >= 2:
                if name_cells[1] != parsed["owner_name"]:
                    parsed["previous_owner"] = name_cells[1]


def _compute_completeness(parsed: dict) -> float:
    expected = ["khata_no", "owner_name", "area_acres", "transfer_date",
                "govt_acquisition_notice", "encumbrance_flag"]
    present = sum(1 for k in expected if parsed.get(k) is not None and
                  (not isinstance(parsed.get(k), bool)))
    present += sum(1 for k in ["govt_acquisition_notice", "encumbrance_flag"]
                   if k in parsed)
    return round(present / len(expected), 2)


class BhoomiRTCParser:

    def parse(self, html: str) -> dict:
        if not html or not isinstance(html, str) or len(html.strip()) < 50:
            logger.warning("[BhoomiRTCParser] Empty or too-short HTML input")
            return {
                "khata_no": None,
                "owner_name": None,
                "previous_owner": None,
                "transfer_date": None,
                "area_acres": None,
                "govt_acquisition_notice": False,
                "govt_acquisition_detail": None,
                "encumbrance_flag": False,
                "encumbrance_detail": None,
                "parser_completeness_score": 0.0,
            }

        parsed: dict = {}

        khata = _find_table_cell(html, "Khata No")
        if not khata:
            khata = _find_table_cell(html, "Khata Number")
        if not khata:
            khata = _find_table_cell(html, "\u0c96\u0cbe\u0ca4\u0cbe \u0cb8\u0c82\u0c96\u0ccd\u0caf\u0cc6")
        if not khata:
            km = _KHATA_PATTERN.search(html)
            if km:
                khata = km.group(1).strip()
        parsed["khata_no"] = khata

        owner = _find_table_cell(html, "Holder Name")
        if not owner:
            owner = _find_table_cell(html, "\u0ca7\u0cbe\u0cb0\u0c95\u0cb0 \u0cb9\u0cc6\u0cb8\u0cb0\u0cc1")
        if not owner:
            holder_table = _extract_table_section(html, "Holder")
            if holder_table:
                rows = re.findall(r"<td[^>]*>\s*(.*?)\s*</td>",
                                  holder_table, re.IGNORECASE | re.DOTALL)
                for row in rows:
                    cleaned = _strip_html(row).strip()
                    if len(cleaned) > 5 and not re.match(r"^[\d\s./\-]+$", cleaned):
                        owner = cleaned
                        break
        parsed["owner_name"] = _strip_html((owner or "")).strip() or None

        _parse_previous_owner(html, parsed)

        date_match = re.search(r"Transfer Date[:\s]*([^<>\n]+)", html, re.IGNORECASE)
        if date_match:
            parsed["transfer_date"] = _normalize_date(date_match.group(1))
        else:
            parsed["transfer_date"] = None

        _parse_area(html, parsed)
        _parse_govt_acquisition(html, parsed)
        _parse_encumbrance(html, parsed)
        parsed["parser_completeness_score"] = _compute_completeness(parsed)
        score = parsed["parser_completeness_score"]
        if score < 0.5:
            logger.warning(
                "[BhoomiRTCParser] Low parsing completeness ({}/6={}) for {} — "
                "HTML format may have changed",
                sum(1 for k in ["khata_no", "owner_name", "area_acres", "transfer_date",
                               "govt_acquisition_notice", "encumbrance_flag"]
                    if parsed.get(k) is not None and
                    (not isinstance(parsed.get(k), bool))),
                score,
                parsed.get("survey_no", "unknown"),
            )

        logger.info(
            "[BhoomiRTCParser] {} — khata={}, owner={}, prev={}, acres={}, "
            "acq={}, enc={}, score={}",
            parsed.get("survey_no", "?"),
            parsed.get("khata_no"),
            parsed.get("owner_name"),
            parsed.get("previous_owner"),
            parsed.get("area_acres"),
            parsed.get("govt_acquisition_notice"),
            parsed.get("encumbrance_flag"),
            parsed.get("parser_completeness_score"),
        )
        return parsed
