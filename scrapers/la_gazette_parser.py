"""
RE_OS — Land Acquisition Gazette Notification Parser (GATE-93, T-1150)

Detects and parses land acquisition notifications from Karnataka Gazette PDFs
issued by KIADB, BDA, and BMRCL. Extracts structured data and writes to
govt_policy_events table as event_type='la_notification'.

Two notification stages:
    - preliminary: Section 4(1) / 17(1) notification — intent to acquire
    - final: Section 6(1) declaration / Section 9 award — acquisition confirmed

Usage:
    parser = LAGazetteParser()
    notifications = parser.parse_pdf("/path/to/gazette.pdf")
    notifications = parser.parse_text(raw_text)
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from loguru import logger

__all__ = ["LAGazetteParser", "LANotification"]

_VILLAGE_INDEX_PATH = os.environ.get(
    "VILLAGE_LOOKUP_PATH",
    "data/kaveri_jurisdiction/village_lookup_index.json",
)

_LA_KEYWORDS = [
    "land acquisition", "preliminary notification", "final notification",
    "section 4", "section 6", "section 17", "kiadb", "bda", "bmrcl",
    "land aquisition", "preliminary notice", "4(1)", "6(1)", "17(1)",
    "notification", "acquire", "acquisition of land",
]

_AUTHORITY_MAP = {
    "kiadb": "KIADB",
    "karnataka industrial areas development board": "KIADB",
    "bda": "BDA",
    "bangalore development authority": "BDA",
    "bmrcl": "BMRCL",
    "bangalore metro rail corporation": "BMRCL",
    "krdcl": "KRDCL",
}

_STAGE_KEYWORDS = {
    "preliminary": [
        "preliminary notification", "section 4", "4(1)", "intention",
        "preliminary notice", "preliminary",
    ],
    "final": [
        "final notification", "section 6", "6(1)", "declaration",
        "award", "section 9", "9(1)", "possession",
    ],
}


class LANotification:
    """Structured land acquisition notification extracted from gazette text."""

    def __init__(
        self,
        notification_no: str = "",
        date_str: str = "",
        authority: str = "",
        purpose: str = "",
        villages: list[str] | None = None,
        survey_nos: list[str] | None = None,
        stage: str = "preliminary",
        source_text: str = "",
    ):
        self.notification_no = notification_no.strip()
        self.date_str = date_str.strip()
        self.authority = authority.strip()
        self.purpose = purpose.strip()
        self.villages = villages or []
        self.survey_nos = survey_nos or []
        self.stage = stage.strip()
        self.source_text = source_text[:2000]

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_no": self.notification_no,
            "date": self.date_str,
            "authority": self.authority,
            "purpose": self.purpose,
            "villages": self.villages,
            "survey_nos": self.survey_nos,
            "stage": self.stage,
        }

    def to_event(self) -> dict[str, Any]:
        """Convert to govt_policy_events-style dict for DB upsert."""
        village_str = ", ".join(self.villages[:5])
        survey_str = ", ".join(self.survey_nos[:10])
        headline = (
            f"LA Notification: {self.authority} — {self.purpose} "
            f"in {village_str}"
        )
        return {
            "headline": headline[:300],
            "category": "infrastructure",
            "subcategory": f"la_notification_{self.stage}",
            "location_text": ", ".join(self.villages),
            "micro_markets": self._infer_markets(),
            "investment_cr": None,
            "stage": self.stage,
            "impact_score": 8 if self.stage == "final" else 6,
            "signal_strength": "high" if self.stage == "final" else "emerging",
            "demand_type": "land_acquisition",
            "time_horizon": "immediate" if self.stage == "final" else "medium",
            "actionability": "accumulate" if self.stage == "final" else "monitor",
            "summary": (
                f"{self.authority} issued {self.stage} notification "
                f"({self.notification_no}) for {self.purpose} "
                f"in {village_str}. Survey nos: {survey_str if survey_str else 'various'}"
            )[:500],
            "why_it_matters": (
                f"Land acquisition for {self.purpose} by {self.authority} in "
                f"{village_str} signals government-driven development that will "
                f"impact land prices in the area."
            )[:500],
            "source_urls": [],
            "published_date": self.date_str[:10] if self.date_str else "",
            "is_north_bengaluru": self._is_north_bengaluru(),
            "event_type": "la_notification",
        }

    def _infer_markets(self) -> list[str]:
        """Map villages to RE_OS market names via jurisdiction index."""
        markets = set()
        for v in self.villages:
            m = self._village_to_market(v)
            if m:
                markets.add(m)
        return list(markets) if markets else ["other"]

    @staticmethod
    def _village_to_market(village: str) -> str | None:
        """Map a village name to RE_OS market via lookup index."""
        try:
            if os.path.exists(_VILLAGE_INDEX_PATH):
                with open(_VILLAGE_INDEX_PATH, encoding="utf-8") as f:
                    idx = json.load(f)
                entry = idx.get(village.strip().lower())
                if entry:
                    return entry.get("market")
            # Fallback: keyword mapping
            vl = village.lower()
            if "yelahanka" in vl or "yelahan" in vl:
                return "Yelahanka"
            if "devanahalli" in vl or "devanahal" in vl:
                return "Devanahalli"
            if "hebbal" in vl:
                return "Hebbal"
            return None
        except Exception:
            return None

    def _is_north_bengaluru(self) -> bool:
        """Check if any villages are in North Bengaluru."""
        nb_keywords = ["yelahanka", "devanahalli", "hebbal", "jakkur",
                       "thanisandra", "bagalur", "nagawara", "doddaballapur"]
        for v in self.villages:
            vl = v.lower()
            for kw in nb_keywords:
                if kw in vl:
                    return True
        return False

    def __repr__(self) -> str:
        return (
            f"LANotification(no={self.notification_no!r}, auth={self.authority!r}, "
            f"stage={self.stage!r}, villages={self.villages})"
        )


class LAGazetteParser:
    """Parse Karnataka Gazette text for land acquisition notifications."""

    def parse_pdf(self, pdf_path: str) -> list[LANotification]:
        """Parse a PDF file for LA notifications."""
        try:
            import pdfplumber
        except ImportError:
            logger.warning("[LAGazetteParser] pdfplumber not installed")
            return []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = ""
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    text += page_text + "\n"
            return self.parse_text(text)
        except Exception as exc:
            logger.warning("[LAGazetteParser] Failed to parse PDF {}: {}", pdf_path, exc)
            return []

    def parse_text(self, text: str) -> list[LANotification]:
        """Parse raw gazette text for one or more LA notifications.

        Detection strategy:
            1. Split text into notification sections by section headers
            2. For each section, detect if it's an LA notification via keywords
            3. Extract structured fields via regex
        """
        if not text or not self._is_la_notification(text):
            return []

        notifications: list[LANotification] = []

        sections = self._split_sections(text)
        for section in sections:
            if not self._is_la_notification(section):
                continue
            notif = self._extract_notification(section)
            if notif.notification_no or notif.authority:
                notifications.append(notif)

        if not notifications and self._is_la_notification(text):
            notif = self._extract_notification(text)
            if notif.notification_no or notif.authority:
                notifications.append(notif)

        return notifications

    def _is_la_notification(self, text: str) -> bool:
        """Check if text contains land acquisition notification keywords."""
        text_lower = text.lower()
        for kw in _LA_KEYWORDS:
            if kw in text_lower:
                return True
        return False

    def _split_sections(self, text: str) -> list[str]:
        """Split gazette text into sections by notification headers."""
        patterns = [
            r'(?=NOTIFICATION\s*(?:NO[.:]?\s*[\w/.-]+))',
            r'(?=Government\s+of\s+Karnataka)',
            r'(?=Karnataka\s+Government\s+Gazette)',
            r'(?=NOTIFICATION)',
        ]
        for pat in patterns:
            parts = re.split(pat, text)
            if len(parts) > 1:
                return [p.strip() for p in parts if len(p.strip()) > 100]
        return [text.strip()] if text.strip() else []

    def _extract_notification(self, text: str) -> LANotification:
        """Extract structured fields from a notification section."""
        notif = LANotification(source_text=text[:2000])

        # Notification number
        no_match = re.search(
            r'NOTIFICATION\s*NO[.:\s]*([A-Z0-9\s./-]+?)(?:\s*Date[.:]|\s*Dated[.:]|\n)',
            text, re.IGNORECASE,
        )
        if no_match:
            notif.notification_no = no_match.group(1).strip()

        # Date
        date_match = re.search(
            r'(?:Date|Dated)[.:]\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            text, re.IGNORECASE,
        )
        if date_match:
            notif.date_str = date_match.group(1).strip()

        # Authority
        auth_match = re.search(
            r'(?:by\s+the\s+)?(KIADB|BDA|BMRCL|KRDCL|Bangalore\s+(?:Development|Metro)\s+(?:Authority|Rail|Corporation)'
            r'|Karnataka\s+Industrial\s+Areas\s+Development\s+Board)',
            text, re.IGNORECASE,
        )
        if auth_match:
            raw = auth_match.group(1).strip()
            raw_lower = raw.lower()
            for alias, canonical in _AUTHORITY_MAP.items():
                if alias in raw_lower:
                    notif.authority = canonical
                    break
            if not notif.authority:
                notif.authority = raw
        else:
            for alias, canonical in _AUTHORITY_MAP.items():
                if alias in text.lower():
                    notif.authority = canonical
                    break

        # Stage — clear before detection so the "if notif.stage: break" sentinel works
        notif.stage = ""
        for stage_name, keywords in _STAGE_KEYWORDS.items():
            for kw in keywords:
                if kw in text.lower():
                    notif.stage = stage_name
                    break
            if notif.stage:
                break
        if not notif.stage:
            notif.stage = "preliminary"

        # Purpose
        purpose_match = re.search(
            r'(?:for\s+the\s+)?(?:acquisition\s+of\s+land\s+)?(?:for\s+)?(.{10,200}?)(?:\.\s*(?:\n|$|Notification))',
            text, re.IGNORECASE | re.DOTALL,
        )
        if purpose_match:
            notif.purpose = purpose_match.group(1).strip()[:200]

        # Villages — match "village(s) of X, Y and Z" patterns
        village_chunks: list[str] = []
        for m in re.finditer(
            r'village[s]?\s+of\s+([\w][\w ,]+?)(?=\s*(?:Taluk|Hobli|District|Survey|Sy\.|\.\s|\n|$))',
            text, re.IGNORECASE,
        ):
            parts = re.split(r'\s*(?:,\s*(?:and\s+)?|and\s+)\s*', m.group(1).strip())
            village_chunks.extend(p.strip() for p in parts if len(p.strip()) > 1)
        # Kannada village markers fallback
        if not village_chunks:
            for m in re.finditer(r'ಗ್ರಾಮ[:\s]*([^\n,]+)', text):
                village_chunks.append(m.group(1).strip())
        notif.villages = list(set(village_chunks))

        # Survey numbers — "Numbers?" handles plurals so "Survey numbers Sy No." doesn't
        # consume the "Sy No." anchor in the same match
        survey_matches = re.findall(
            r'(?:Sy[.\s]*No[.\s]*[:.\s]*|Survey\s+Numbers?[.\s]*|S\.?No\.?[:.\s]*)(\d[\d\s,/&\-A-Za-z]*)',
            text, re.IGNORECASE,
        )
        for m in survey_matches:
            nums = re.findall(r'(\d+[/\-]?\d*[A-Za-z]*)', m)
            notif.survey_nos.extend(nums)
        notif.survey_nos = list(set(notif.survey_nos))

        return notif


def run_la_notification_scan() -> int:
    """Scheduler entry point: scan for new LA notifications from configured sources."""
    total = 0
    sources = _get_la_gazette_sources()
    for source in sources:
        try:
            parser = LAGazetteParser()
            notifications = parser.parse_pdf(source["path"])
            for n in notifications:
                event = n.to_event()
                _upsert_la_event(event)
                total += 1
                if n._is_north_bengaluru() and n.stage == "final":
                    _send_la_alert(n)
        except Exception as exc:
            logger.warning("[LANotification] Failed to scan {}: {}", source.get("path", "?"), exc)

    logger.info("[LANotification] Scan complete: {} notifications", total)
    return total


def _get_la_gazette_sources() -> list[dict]:
    """Return configured LA gazette PDF sources."""
    sources_str = os.environ.get("LA_GAZETTE_SOURCES", "[]")
    try:
        return json.loads(sources_str)
    except (json.JSONDecodeError, TypeError):
        return []


def _upsert_la_event(event: dict) -> bool:
    """Insert LA notification event into govt_policy_events table.

    Uses two-phase dedup: SELECT by headline hash, then INSERT or UPDATE.
    This avoids requiring a UNIQUE constraint on source_id column
    which may not exist on the table.
    """
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().begin() as conn:
            existing = conn.execute(
                text("SELECT id, impact_score, stage FROM govt_policy_events WHERE headline = :hl LIMIT 1"),
                {"hl": event["headline"][:300]},
            ).fetchone()

            if existing:
                conn.execute(
                    text("""
                        UPDATE govt_policy_events
                        SET impact_score = :impact_score,
                            signal_strength = :signal_strength,
                            stage = :stage,
                            summary = :summary
                        WHERE id = :eid
                    """),
                    {
                        "impact_score": event["impact_score"],
                        "signal_strength": event["signal_strength"],
                        "stage": event["stage"],
                        "summary": event["summary"][:500],
                        "eid": existing[0],
                    },
                )
            else:
                conn.execute(
                    text("""
                        INSERT INTO govt_policy_events
                            (headline, category, subcategory, location_text,
                             micro_markets, investment_cr, stage, impact_score,
                             signal_strength, demand_type, time_horizon,
                             actionability, summary, why_it_matters,
                             source_urls, published_date, is_north_bengaluru)
                        VALUES
                            (:headline, :category, :subcategory, :location_text,
                             :micro_markets, :investment_cr, :stage, :impact_score,
                             :signal_strength, :demand_type, :time_horizon,
                             :actionability, :summary, :why_it_matters,
                             :source_urls, :published_date, :is_north_bengaluru)
                    """),
                    {
                        "headline": event["headline"][:300],
                        "category": event["category"],
                        "subcategory": event["subcategory"],
                        "location_text": event["location_text"],
                        "micro_markets": event["micro_markets"],
                        "investment_cr": event["investment_cr"],
                        "stage": event["stage"],
                        "impact_score": event["impact_score"],
                        "signal_strength": event["signal_strength"],
                        "demand_type": event["demand_type"],
                        "time_horizon": event["time_horizon"],
                        "actionability": event["actionability"],
                        "summary": event["summary"],
                        "why_it_matters": event["why_it_matters"],
                        "source_urls": event.get("source_urls", []),
                        "published_date": event.get("published_date", ""),
                        "is_north_bengaluru": event.get("is_north_bengaluru", False),
                    },
                )
        return True
    except Exception as exc:
        logger.warning("[LANotification] DB upsert failed: {}", exc)
        return False


def _send_la_alert(notification: LANotification) -> None:
    """Send Discord alert for LA notification in covered market village."""
    try:
        from utils.discord_notifier import send
        village_str = ", ".join(notification.villages[:3])
        msg = (
            f"📍 **Land Acquisition — {notification.authority}**\n"
            f"Stage: {notification.stage.upper()}\n"
            f"Purpose: {notification.purpose[:200]}\n"
            f"Villages: {village_str}\n"
            f"Notification: {notification.notification_no}"
        )
        send("govt_policy_scout", f"LA Notification — {notification.authority}", msg)
    except Exception as exc:
        logger.debug("[LANotification] Discord alert failed: {}", exc)
