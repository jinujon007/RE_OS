"""
RE_OS — Karnataka IGR Gazette PDF Parser
─────────────────────────────────────────
Downloads and parses official Karnataka Stamp & Registration Dept gazette PDFs
to extract locality-level guidance values (circle rates).

Source: https://igr.karnataka.gov.in/page/Revised+Guidelines+Value/en
PDFs: 2023-24 Gazette-CVC/ — one file per sub-registrar office

Data format in PDFs (multilingual — Kannada + English):
  <sl_no>  <kannada_name>  <english_name>  [property_ids/survey_nos]  <psm_value>
  Values are in ₹ per square metre. Convert: psf = psm / 10.764

The BDA Corrigendum Gazette has revision rates for BDA-layout areas —
parsed the same way; supersedes base gazette where available.
"""
from __future__ import annotations

import io
import re
from datetime import date
from typing import Iterator

import requests
from loguru import logger

__all__ = ["GVRecord", "GazetteParser"]

_SQM_TO_SQFT = 10.764

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://igr.karnataka.gov.in/",
}

# Official gazette PDFs per market (2023-24 fiscal year)
# Each market may have multiple SRO PDFs; all are parsed and merged.
IGR_GAZETTE_PDFS: dict[str, list[dict]] = {
    "Yelahanka": [
        {
            "url": "https://igr.karnataka.gov.in/storage/pdf-files/2023-24%20Gazette-CVC/Yalahanka.pdf",
            "sro": "Yalahanka",
            "effective_from": "2023-04-01",
            "gazette_year": "2023-24",
        },
        {
            "url": "https://igr.karnataka.gov.in/storage/pdf-files/2023-24%20Gazette-CVC/Jala.pdf",
            "sro": "Jala",
            "effective_from": "2023-04-01",
            "gazette_year": "2023-24",
        },
        {
            "url": "https://igr.karnataka.gov.in/storage/pdf-files/BDA%20corrigendum%20Gazette/Yalahanka.pdf",
            "sro": "Yalahanka",
            "effective_from": "2024-04-01",
            "gazette_year": "2023-24 BDA Corrigendum",
        },
        {
            "url": "https://igr.karnataka.gov.in/storage/pdf-files/BDA%20corrigendum%20Gazette/Jala.pdf",
            "sro": "Jala",
            "effective_from": "2024-04-01",
            "gazette_year": "2023-24 BDA Corrigendum",
        },
    ],
    "Devanahalli": [
        {
            "url": "https://igr.karnataka.gov.in/storage/pdf-files/2023-24%20Gazette-CVC/Devanahalli.pdf",
            "sro": "Devanahalli",
            "effective_from": "2023-04-01",
            "gazette_year": "2023-24",
        },
    ],
    "Hebbal": [
        {
            "url": "https://igr.karnataka.gov.in/storage/pdf-files/2023-24%20Gazette-CVC/Hebbal.pdf",
            "sro": "Hebbal",
            "effective_from": "2023-04-01",
            "gazette_year": "2023-24",
        },
    ],
}

# Kaveri API SRO codes for registration volume
SRO_CODES: dict[str, int] = {
    "Yelahanka": 224,      # Jala SRO covers Yelahanka New Town corridor
    "Devanahalli": 118,
    "Hebbal": 208,
}


_GAZETTE_YEAR_HEADER_RE = re.compile(
    r"BENGALURU,\s*(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY),?\s+.*?(\d{4})"
)
_GAZETTE_YEAR_FILENAME_RE = re.compile(r"(\d{4})")


class GVRecord:
    """One guidance-value row extracted from a gazette PDF."""

    __slots__ = (
        "locality", "property_type", "road_type",
        "guidance_value_psf", "guidance_value_per_sqm",
        "effective_from", "source_document", "sro", "gazette_year",
        "gazette_year_int", "gazette_published_date",
        "extraction_confidence",
    )

    def __init__(
        self,
        locality: str,
        psm: float,
        effective_from: str,
        source_document: str,
        sro: str,
        gazette_year: str,
        property_type: str = "Residential",
        extraction_confidence: float = 0.7,
        gazette_year_int: int | None = None,
        gazette_published_date: str | None = None,
    ) -> None:
        self.locality = locality
        self.guidance_value_per_sqm = psm
        self.guidance_value_psf = round(psm / _SQM_TO_SQFT, 2)
        self.effective_from = effective_from
        self.source_document = source_document
        self.sro = sro
        self.gazette_year = gazette_year
        self.property_type = property_type
        self.road_type = "Main Road"  # gazette doesn't distinguish consistently
        self.extraction_confidence = extraction_confidence
        self.gazette_year_int = gazette_year_int
        self.gazette_published_date = gazette_published_date

    def to_dict(self) -> dict:
        d = {
            "locality": self.locality,
            "property_type": self.property_type,
            "road_type": self.road_type,
            "guidance_value_psf": self.guidance_value_psf,
            "guidance_value_per_sqm": self.guidance_value_per_sqm,
            "effective_from": self.effective_from,
            "source_document": self.source_document,
            "source": "igr_gazette",
            "sro": self.sro,
            "gazette_year": self.gazette_year,
        }
        if self.gazette_year_int is not None:
            d["gazette_year_int"] = self.gazette_year_int
        if self.gazette_published_date is not None:
            d["gazette_published_date"] = self.gazette_published_date
        return d


class GazetteParser:
    """
    Downloads and parses Karnataka IGR guidance-value gazette PDFs.

    Usage:
        parser = GazetteParser()
        records = parser.scrape_guidance_values("Yelahanka")
        # returns list[dict] compatible with guidance_values table schema
    """

    def scrape_guidance_values(self, market: str) -> list[dict]:
        """
        Returns list of guidance-value dicts for the given market.
        All dicts have source='igr_gazette' and are ready for DB upsert.

        Returns empty list if all PDF downloads fail — never raises.
        """
        pdfs = IGR_GAZETTE_PDFS.get(market, [])
        if not pdfs:
            logger.warning("[GazetteParser] No gazette PDFs configured for market={}", market)
            return []

        all_records: list[dict] = []
        for pdf_spec in pdfs:
            try:
                records = self._parse_pdf(pdf_spec)
                logger.info(
                    "[GazetteParser][{}][{}] {} GV records from gazette PDF",
                    market, pdf_spec["sro"], len(records),
                )
                all_records.extend(records)
            except Exception as exc:
                logger.warning(
                    "[GazetteParser] Failed to parse {} gazette: {}",
                    pdf_spec.get("sro", "?"), exc,
                )

        if not all_records:
            logger.warning("[GazetteParser] All gazette PDFs failed for market={}", market)
        return all_records

    def scrape_registration_velocity_signal(
        self, market: str, from_date: str, to_date: str
    ) -> dict:
        """Alias used by DemandIntel — same as scrape_registration_volume."""
        return self.scrape_registration_volume(market, from_date, to_date)

    def scrape_registration_volume(
        self, market: str, from_date: str, to_date: str
    ) -> dict:
        """
        Fetches daily registration counts from Kaveri 2.0 API for the market's SRO.

        Returns dict with keys: market, sro_code, applications_received,
        applications_approved, from_date, to_date, source.
        Returns empty dict on failure.
        """
        sro_code = SRO_CODES.get(market)
        if not sro_code:
            logger.debug("[GazetteParser] No SRO code for market={}", market)
            return {}

        # ApplicationTypeid=13 is the type that returns non-zero data with SRO filter
        # (verified live: ApplicationTypeid=1 returns 0 for all SROs)
        url = (
            f"https://kaveri.karnataka.gov.in/api/GetCitizenDashboard"
            f"?ApplicationTypeid=13&FromDate={from_date}&ToDate={to_date}"
            f"&PropertyTypeid=0&SroCode={sro_code}"
        )
        headers = {
            "User-Agent": _HEADERS["User-Agent"],
            "Accept": "application/json",
            "Referer": "https://kaveri.karnataka.gov.in/",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200 and resp.text.strip():
                body = resp.json()
                data = body.get("data", body)
                return {
                    "market": market,
                    "sro_code": sro_code,
                    "applications_received": data.get("applicationsReceived", 0),
                    "applications_approved": data.get("applicationsApproved", 0),
                    "applications_pending": data.get("applicationsPending", 0),
                    "from_date": from_date,
                    "to_date": to_date,
                    "source": "kaveri_api",
                }
        except Exception as exc:
            logger.debug("[GazetteParser] Registration volume API failed for {}: {}", market, exc)
        return {}

    @staticmethod
    def _extract_gazette_year(text: str, pdf_url: str) -> int:
        """Extract gazette publication year from PDF header or filename.

        Priority:
          1. Header regex: BENGALURU, MONDAY ... 2024
          2. PDF filename year pattern: /path/to/2024/file.pdf
          3. Fallback: current_year - 1
        """
        from datetime import date
        m = _GAZETTE_YEAR_HEADER_RE.search(text)
        if m:
            return int(m.group(1))
        m = _GAZETTE_YEAR_FILENAME_RE.search(pdf_url)
        if m:
            year = int(m.group(1))
            if 1900 <= year <= 2100:
                return year
        return date.today().year - 1

    def _parse_pdf(self, pdf_spec: dict) -> list[dict]:
        """Download a gazette PDF and extract guidance-value records."""
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError("pdfplumber not installed — required for gazette parsing")

        url = pdf_spec["url"]
        resp = requests.get(url, headers=_HEADERS, timeout=45)
        resp.raise_for_status()

        records: list[dict] = []
        gazette_year_int = None
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                # Extract gazette year from first page header
                if gazette_year_int is None and text.strip():
                    gazette_year_int = self._extract_gazette_year(text, url)
                for rec in self._extract_records_from_page(text, pdf_spec):
                    if gazette_year_int is not None:
                        rec["gazette_year_int"] = gazette_year_int
                    records.append(rec)

        return records

    @staticmethod
    def _clamp_confidence(conf: float) -> float:
        """Clamp extraction_confidence to [0.0, 1.0]."""
        return max(0.0, min(1.0, conf))

    def _extract_records_from_page(
        self, text: str, pdf_spec: dict
    ) -> Iterator[dict]:
        """
        Yield GV records from one page of gazette text.

        Row format (Kannada + English mixed):
          <sl_no>  <kannada_text>  <English locality name>  [survey/property IDs]  <psm_value>

        Strategy:
          1. Detect Kannada chars for extraction_confidence.
          2. Strip non-English characters before regex passes.
          3. Split into lines.
          4. For each line, find the last standalone 4–6 digit integer — that's the PSM rate.
          5. Extract the English name (ASCII sequences after Kannada text).
          6. Skip lines that look like headers, page numbers, or boilerplate.
        """
        # Determine page-level confidence
        has_kannada = bool(self._KANNADA_RE.search(text))
        page_confidence = self._clamp_confidence(1.0 if not has_kannada else 0.7)

        # Strip Kannada characters to prevent corruption of number patterns
        text = self._extract_english_only(text)

        lines = text.split("\n")
        for line in lines:
            rec = self._parse_line(line.strip(), pdf_spec)
            if rec:
                if "extraction_confidence" not in rec:
                    rec["extraction_confidence"] = page_confidence
                else:
                    rec["extraction_confidence"] = self._clamp_confidence(rec["extraction_confidence"])
                yield rec

    _SKIP_PHRASES = frozenset([
        "hobli", "village/area", "property id", "per sq", "sqm", "built",
        "sl.no", "sl no", "gazette", "karnataka", "department", "revised",
        "guideline", "registration", "office", "ward", "division",
    ])

    # Regex: last standalone 4–6 digit integer on a line, not part of a fraction or ID
    _PSM_RE = re.compile(r'(?<![/\-\w])(\d{4,6})(?!\s*[/\-\w])\s*$')

    # Kannada Unicode block (U+0C80–U+0CFF)
    _KANNADA_RE = re.compile(r'[ಀ-೿‌‍]+')

    # Characters to keep in _extract_english_only: ASCII printable + ₹
    _ENGLISH_ONLY_KEEP = re.compile(r'[^\x20-\x7E\u20B9\r\n]')

    @staticmethod
    def _extract_english_only(text: str) -> str:
        """Strip all characters outside ASCII printable + ₹ + newlines."""
        return GazetteParser._ENGLISH_ONLY_KEEP.sub('', text)

    # Property ID patterns to discard as locality names
    _PROP_ID_RE = re.compile(
        r'^(?:PID|SY|No\.?|Sy\.?|No|khata|katha)'
        r'|\d{3}-[WwMm]\d{4,}',
        re.I,
    )

    def _clean_locality(self, raw: str) -> str:
        """
        Clean extracted English locality name — remove noise, spacing artefacts.

        The main challenge: pdfplumber maps some Kannada font glyphs to ASCII
        characters (single letters like "A", "C", "P", "D") which get interleaved
        with the real English text. We filter these out by requiring word-length ≥ 3.
        """
        # Remove Kannada Unicode block characters
        name = self._KANNADA_RE.sub(' ', raw)
        # Remove property ID patterns like "003-W0022-6", "004-M0010-1", "003-W-0178-1"
        name = re.sub(r'\b\d{3}-[WwMmCc]-?\d[\d\-]+\b', '', name)
        # Remove survey number suffixes like "Sy No. 30/2B", "Sy Nos. 78 79 80"
        name = re.sub(r'\b(?:Sy|SY|sy)\.?\s+No(?:s)?\.?\s*[\d/\-,\s]+', '', name)
        # Remove CVC approval codes like "(CVC/235/2018-19, 20/4/2019)"
        name = re.sub(r'\(?CVC/[^)]+\)?', '', name)
        name = re.sub(r'\(D\.R\.O[^)]+\)', '', name)
        # Remove katha/khata references
        name = re.sub(r'\b(?:Katha|Khata)\s+No\.?\s*[\d/\-,\s]+', '', name, flags=re.I)
        # Remove trailing standalone numbers (survey counts, plot IDs)
        name = re.sub(r'\s+\d{1,6}(\s+\d{1,6})*\s*$', '', name)
        # Remove trailing/leading punctuation
        name = re.sub(r'[,\-\.()]+$', '', name)
        name = re.sub(r'^[,\-\.\s()]+', '', name)
        # Collapse multiple spaces
        name = re.sub(r'\s{2,}', ' ', name).strip()

        # Drop single/double-character tokens (Kannada font artifacts)
        tokens = name.split()
        clean_tokens = [t for t in tokens if len(t) >= 3 or (len(t) >= 2 and t.isdigit() is False and not t.isupper())]
        name = " ".join(clean_tokens).strip()

        # Final quality check
        alpha_count = sum(c.isalpha() for c in name)
        isolated_singles = sum(1 for t in name.split() if len(t) == 1 and t.isalpha())
        if alpha_count < 5 or isolated_singles > 2:
            return ""
        if self._PROP_ID_RE.search(name) and alpha_count < 8:
            return ""
        return name[:120]

    def _parse_line(self, line: str, pdf_spec: dict) -> dict | None:
        if not line or len(line) < 8:
            return None

        lower = line.lower()
        if any(p in lower for p in self._SKIP_PHRASES):
            return None

        # Must end with (or close to) a 4-6 digit rate
        # Allow optional small trailing number (survey count like "227", "304")
        # Pattern: "...  35000 227" → rate=35000, trailing=227 (ignored)
        # Pattern: "...  35000"     → rate=35000
        used_fallback = False
        rate_match = self._PSM_RE.search(line)
        if not rate_match:
            alt = re.search(r'(?<![/\-\w])(\d{4,6})\s+\d{1,3}\s*$', line)
            if alt:
                rate_match = alt
                used_fallback = True
            else:
                return None

        try:
            psm = int(rate_match.group(1))
        except (IndexError, ValueError):
            return None

        if not (1_000 <= psm <= 200_000):
            return None

        # Extract English locality name — ASCII sequences only
        english_parts = re.findall(r"[A-Za-z][A-Za-z0-9 .,\-/()'&]+", line)
        raw_locality = " ".join(p.strip() for p in english_parts)

        # Strip the rate value itself if it ended up in the name
        raw_locality = re.sub(rf'\b{psm}\b', '', raw_locality).strip()

        locality = self._clean_locality(raw_locality)
        if not locality:
            return None

        rec = GVRecord(
            locality=locality,
            psm=float(psm),
            effective_from=pdf_spec["effective_from"],
            source_document=pdf_spec["url"],
            sro=pdf_spec["sro"],
            gazette_year=pdf_spec["gazette_year"],
        )
        result = rec.to_dict()
        if used_fallback:
            result["extraction_confidence"] = 0.5
        return result
