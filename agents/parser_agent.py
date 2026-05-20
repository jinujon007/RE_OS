"""
RE_OS — Parser Agent
─────────────────────
Takes raw HTML/JSON from the Scraper and extracts clean, structured data.
Uses Ollama locally — this is the heavy text processing work that would
burn Claude tokens if done here. Let the free model do it.
"""

from crewai import Agent
from crewai.tools import BaseTool
from bs4 import BeautifulSoup
import json
import re
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.llm_router import get_light_llm


class RERAParserTool(BaseTool):
    name: str = "rera_parser"
    description: str = (
        "Parses raw RERA project data (HTML or JSON) into a clean, structured "
        "JSON object matching the RE_OS database schema. "
        "Input: raw RERA project data string. "
        "Output: structured dict with project_name, rera_number, developer, "
        "units, pricing, dates, status."
    )

    def _run(self, raw_data: str) -> str:
        try:
            # Try to parse as JSON first (if already structured)
            data = json.loads(raw_data)
            return json.dumps(self._normalize_rera_record(data), indent=2)
        except json.JSONDecodeError:
            # It's HTML — extract text first
            soup = BeautifulSoup(raw_data, "lxml")
            text = soup.get_text(separator=" ", strip=True)
            return json.dumps(
                {"raw_text": text[:5000], "needs_llm_parse": True}, indent=2
            )

    def _normalize_rera_record(self, data: dict) -> dict:
        """Normalize field names and types from RERA raw data."""
        normalized = {}

        # RERA number — look for PRM/KA/... pattern
        rera_num = (
            data.get("reraNo")
            or data.get("rera_number")
            or data.get("registrationNumber")
            or data.get("projectRno")
            or ""
        )
        normalized["rera_number"] = rera_num.strip()

        # Project name
        normalized["project_name"] = (
            data.get("projectName")
            or data.get("project_name")
            or data.get("name")
            or ""
        ).strip()

        # Developer/Promoter
        normalized["developer_name"] = (
            data.get("promoterName")
            or data.get("developer_name")
            or data.get("promoter")
            or ""
        ).strip()

        # Units
        normalized["total_units"] = self._to_int(
            data.get("totalUnits")
            or data.get("total_units")
            or data.get("noOfUnits")
            or 0
        )
        normalized["sold_units"] = self._to_int(
            data.get("soldUnits")
            or data.get("sold_units")
            or data.get("bookedUnits")
            or 0
        )
        normalized["unsold_units"] = self._to_int(
            data.get("unsoldUnits")
            or data.get("unsold_units")
            or data.get("availableUnits")
            or 0
        )

        # If unsold not given, calculate
        if normalized["unsold_units"] == 0 and normalized["total_units"] > 0:
            normalized["unsold_units"] = (
                normalized["total_units"] - normalized["sold_units"]
            )

        # Location
        normalized["district"] = data.get("district", "").strip()
        normalized["taluk"] = data.get("taluk", "").strip()
        normalized["locality"] = (
            data.get("locality")
            or data.get("projectLocality")
            or data.get("address")
            or ""
        ).strip()

        # Status
        normalized["project_status"] = (
            data.get("projectStatus")
            or data.get("project_status")
            or data.get("status")
            or ""
        ).strip()

        # Dates
        normalized["possession_date"] = data.get("possessionDate") or data.get(
            "possession_date"
        )
        normalized["registration_date"] = data.get("registrationDate") or data.get(
            "registration_date"
        )

        # Project type
        normalized["project_type"] = (
            data.get("projectType")
            or data.get("project_type")
            or data.get("type")
            or "Residential"
        ).strip()

        # Preserve raw
        normalized["raw_data"] = data

        return normalized

    def _to_int(self, value) -> int:
        try:
            return int(str(value).replace(",", "").strip())
        except (ValueError, TypeError):
            return 0


class PriceParserTool(BaseTool):
    name: str = "price_parser"
    description: str = (
        "Extracts and normalizes price information from listing data. "
        "Converts Indian price formats (₹45L, ₹1.2Cr, 4500/sqft) into "
        "clean numeric values in INR. "
        "Input: price string or listing dict. Output: normalized price dict."
    )

    def _run(self, price_input: str) -> str:
        try:
            data = json.loads(price_input)
            price_str = str(data.get("price", price_input))
        except (json.JSONDecodeError, TypeError):
            price_str = str(price_input)

        result = self._parse_price(price_str)
        return json.dumps(result)

    def _parse_price(self, price_str: str) -> dict:
        price_str = (
            price_str.replace(",", "").replace("₹", "").replace("Rs", "").strip()
        )

        # Match patterns like 1.2Cr, 45L, 4500 psf
        cr_match = re.search(r"([\d.]+)\s*[Cc]r", price_str)
        l_match = re.search(r"([\d.]+)\s*[Ll]", price_str)
        plain_match = re.search(r"([\d.]+)", price_str)

        if cr_match:
            amount = float(cr_match.group(1)) * 10_000_000
            return {"amount_inr": int(amount), "display": price_str, "unit": "crore"}
        elif l_match:
            amount = float(l_match.group(1)) * 100_000
            return {"amount_inr": int(amount), "display": price_str, "unit": "lakh"}
        elif plain_match:
            return {
                "amount_inr": int(float(plain_match.group(1))),
                "display": price_str,
                "unit": "absolute",
            }

        return {"amount_inr": None, "display": price_str, "unit": "unknown"}


def create_parser_agent() -> Agent:
    return Agent(
        role="Data Extraction and Structuring Specialist",
        goal=(
            "Transform raw scraped data (messy HTML, inconsistent JSON, "
            "Indian price formats, mixed locality spellings) into clean, "
            "normalized records ready for the RE_OS database. "
            "Zero tolerance for bad data entering the system."
        ),
        backstory=(
            "You are a data engineer who has spent years cleaning Indian government "
            "database exports. You know RERA Karnataka's inconsistent field naming. "
            "You know that '45 Lakhs' and '45L' and '₹45,00,000' are all the same number. "
            "You know that 'Yelahanka' and 'Yelahanka New Town' are different localities. "
            "Your job is to bring order to chaos — take messy scraped data and produce "
            "clean, typed, normalized JSON that matches the RE_OS schema exactly. "
            "If data is missing, mark it NULL. Never invent values."
        ),
        tools=[
            RERAParserTool(),
            PriceParserTool(),
        ],
        llm=get_light_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
