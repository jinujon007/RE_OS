"""
RE_OS — Content Writer Agent (Sprint 53 — PR & Brand Department)
Role: produce LinkedIn posts, Instagram captions, project brief sections,
and email subject lines from a PRBrief + IntelPackage data.
Uses LIGHT LLM tier (Cerebras). Enforces LLS brand voice.
"""

import json
import textwrap
import concurrent.futures
from dataclasses import dataclass, field, asdict

from loguru import logger

from agents.pr_head_agent import PRBrief, LLS_BRAND_VOICE_CONSTRAINTS

__all__ = ["ContentPack", "ContentWriterAgent", "SECTION_NAMES"]

_LLM_IMPORTED = False
try:
    from config.llm_router import get_light_llm as _get_light_llm, get_analysis_llm as _get_analysis_llm
    _LLM_IMPORTED = True
except ImportError:
    logger.warning("[ContentWriter] config.llm_router not available — will use fallback only")


SECTION_NAMES = [
    "Overview",
    "Market Context",
    "Product Concept",
    "Financial Case",
    "Risk Landscape",
    "Team & Track Record",
    "Call to Action",
]


def _word_boundary_truncate(text: str, max_chars: int, suffix: str = " ...") -> str:
    """Truncate at word boundary, never splitting words."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars - len(suffix)]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.6:
        truncated = truncated[:last_space]
    return truncated.strip() + suffix


@dataclass
class ContentPack:
    linkedin_post: str = ""
    instagram_caption: str = ""
    project_brief_sections: list[dict] = field(default_factory=list)
    email_subject: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ContentWriterAgent:
    """Content Writer Agent — produces ContentPack from PRBrief + market data.

    Uses LIGHT LLM tier (Cerebras). Falls back through ANALYSIS → Ollama.
    Enforces same LLS brand voice as PR Head.
    """

    _LLM_TIMEOUT_S = 45

    def __init__(self, temperature: float = 0.2):
        self.temperature = temperature

    def _build_system_prompt(self) -> str:
        return (
            "You are the Content Writer for LLS (Lavish Life Styles), a premium real estate "
            "developer in North Bengaluru. You transform PR briefs and market intelligence "
            "into polished, ready-to-publish content across channels.\n\n"
            f"{LLS_BRAND_VOICE_CONSTRAINTS}\n\n"
            "Your content style guidelines:\n"
            "- Professional, confident, and warm — never hype-driven or salesy\n"
            "- No emoji in LinkedIn posts or email subjects\n"
            "- Instagram can use relevant hashtags (max 5)\n"
            "- Every claim must trace back to data in the brief\n"
            "- Closing CTA in LinkedIn posts (e.g., 'DM for the full brief')\n\n"
            "Output format: strict JSON with keys:\n"
            "- linkedin_post: str (<=280 chars, no emoji, ends with CTA)\n"
            "- instagram_caption: str (<=150 chars + 5 hashtags as space-separated string)\n"
            "- project_brief_sections: list of 7 dicts, each with {title, body, word_count}\n"
            "- email_subject: str (<=60 chars)"
        )

    def _build_prompt(self, brief: PRBrief, psf: float, irr: float, market: str) -> str:
        diffs = "\n".join(f"  - {d}" for d in brief.key_differentiators[:5])
        risks = "\n".join(f"  - {r}" for r in brief.risk_acknowledgements[:3])

        sections_instruction = "\n".join(
            f"  {i+1}. {name}" for i, name in enumerate(SECTION_NAMES)
        )

        return (
            f"Generate a ContentPack from the following PR Brief:\n\n"
            f"Project Tagline: {brief.project_tagline}\n"
            f"Market: {market}\n"
            f"Average PSF: ₹{psf:,.0f}\n"
            f"IRR: {irr:.1f}%\n"
            f"Target Segment: {brief.target_segment}\n\n"
            f"Key Differentiators:\n{diffs}\n\n"
            f"Risk Acknowledgements:\n{risks}\n\n"
            f"Investor Narrative:\n{brief.investor_narrative[:500]}\n\n"
            f"Generate ALL of the following:\n"
            f"1. LinkedIn post (<=280 chars, no emoji, professional, ends with CTA like "
            f"'DM for the full deal memo.')\n"
            f"2. Instagram caption (<=150 chars + 5 relevant hashtags)\n"
            f"3. Project brief with exactly 7 sections:\n{sections_instruction}\n"
            f"   Each section: {{title, body (50-200 words), word_count}}\n"
            f"4. Email subject line (<=60 chars)\n\n"
            "Return as JSON dict with keys: linkedin_post, instagram_caption, "
            "project_brief_sections, email_subject"
        )

    def _get_llm_with_fallback(self):
        """Return LIGHT tier LLM, falling back to ANALYSIS then heavy."""
        if not _LLM_IMPORTED:
            raise ImportError("config.llm_router not available")
        try:
            return _get_light_llm(temperature=self.temperature)
        except Exception:
            logger.debug("[ContentWriter] Light LLM unavailable, trying analysis tier")
        try:
            return _get_analysis_llm(temperature=self.temperature)
        except Exception:
            logger.debug("[ContentWriter] Analysis LLM unavailable, trying heavy tier")
        from config.llm_router import get_heavy_llm
        return get_heavy_llm(temperature=self.temperature)

    def _parse_llm_response(self, raw: str) -> ContentPack:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            try:
                start = raw.index("{")
                end = raw.rindex("}") + 1
                data = json.loads(raw[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.warning("[ContentWriter] Failed to parse LLM output, using fallback")
                return self._fallback_content_pack()

        linkedin = str(data.get("linkedin_post", ""))
        instagram = str(data.get("instagram_caption", ""))
        email_subject = str(data.get("email_subject", ""))
        sections = list(data.get("project_brief_sections", []))[:7]

        linkedin = _word_boundary_truncate(linkedin, 280)
        email_subject = _word_boundary_truncate(email_subject, 60, "...")

        if len(instagram) > 150 and "#" in instagram:
            hash_idx = instagram.index("#")
            body = _word_boundary_truncate(instagram[:hash_idx], 100)
            hashtags = instagram[hash_idx:].split()[:5]
            instagram = f"{body} {' '.join(hashtags)}"

        validated_sections = []
        for s in sections:
            if isinstance(s, dict) and "title" in s and "body" in s:
                validated_sections.append(s)
        if len(validated_sections) != 7:
            validated_sections = self._build_default_sections()

        return ContentPack(
            linkedin_post=linkedin,
            instagram_caption=instagram,
            project_brief_sections=validated_sections,
            email_subject=email_subject,
        )

    def _build_default_sections(self) -> list[dict]:
        return [
            {"title": "Overview", "body": "Project overview data not generated.", "word_count": 5},
            {"title": "Market Context", "body": "Market context not generated.", "word_count": 4},
            {"title": "Product Concept", "body": "Product concept not generated.", "word_count": 4},
            {"title": "Financial Case", "body": "Financial case not generated.", "word_count": 4},
            {"title": "Risk Landscape", "body": "Risk landscape not generated.", "word_count": 4},
            {"title": "Team & Track Record", "body": "Team details not generated.", "word_count": 4},
            {"title": "Call to Action", "body": "Contact LLS for the full deal memorandum.", "word_count": 7},
        ]

    def _fallback_content_pack(self) -> ContentPack:
        return ContentPack(
            linkedin_post="North Bengaluru's next landmark development. DM for the full deal memo.",
            instagram_caption="North Bengaluru's next landmark. #BengaluruRealEstate #LLS",
            project_brief_sections=self._build_default_sections(),
            email_subject="North Bengaluru — Investment Brief",
        )

    def run(self, brief: PRBrief, psf: float = 0.0, irr: float = 0.0, market: str = "") -> ContentPack:
        """Execute Content Writer Agent.

        Args:
            brief: PRBrief from PR Head Agent
            psf: Average PSF for context
            irr: Projected IRR for context
            market: Market name

        Returns:
            ContentPack with LinkedIn post, Instagram caption, project brief sections, email subject.
        """
        if not _LLM_IMPORTED:
            logger.warning("[ContentWriter] LLM router unavailable — using fallback")
            return self._fallback_content_pack()

        try:
            llm = self._get_llm_with_fallback()
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_prompt(brief, psf, irr, market)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    llm.invoke,
                    [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}]
                )
                response = future.result(timeout=self._LLM_TIMEOUT_S)

            raw_text = ""
            if hasattr(response, "content"):
                raw_text = response.content
            elif isinstance(response, str):
                raw_text = response
            else:
                raw_text = str(response)

            content_pack = self._parse_llm_response(raw_text)
            logger.info(
                "[ContentWriter] ContentPack generated — LinkedIn: %d chars, sections: %d",
                len(content_pack.linkedin_post),
                len(content_pack.project_brief_sections),
            )
            return content_pack

        except concurrent.futures.TimeoutError:
            logger.warning("[ContentWriter] LLM timed out after %ds — using fallback", self._LLM_TIMEOUT_S)
            return self._fallback_content_pack()
        except (ImportError, ConnectionError, OSError, ValueError) as exc:
            logger.warning("[ContentWriter] LLM call failed: %s — using fallback", exc)
            return self._fallback_content_pack()
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            logger.warning("[ContentWriter] Unexpected error: %s — using fallback", exc)
            return self._fallback_content_pack()
