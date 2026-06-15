"""
RE_OS — Social Media Agent (Sprint 59 — PR Dept Completion)
Generates weekly social media content calendar from PRBrief + market data.
Uses LIGHT LLM tier with same brand voice constraints as PR Head.

Thread-safe. Never raises on LLM failure — falls back to structured calendar.
"""

import json
import concurrent.futures
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from threading import Lock
from typing import Any
from loguru import logger

from agents.pr_head_agent import PRBrief, LLS_BRAND_VOICE_CONSTRAINTS

__all__ = [
    "PostDraft",
    "WeekPlan",
    "SocialCalendar",
    "ContentCalendarGenerator",
    "PostFormatter",
    "SocialMediaAgent",
]

_LLM_IMPORTED = False
_LLM_IMPORT_LOCK = Lock()
try:
    from config.llm_router import get_light_llm as _get_light_llm
    from config.llm_router import get_analysis_llm as _get_analysis_llm

    _LLM_IMPORTED = True
except ImportError:
    logger.warning(
        "[SocialMedia] config.llm_router not available — will use fallback only"
    )


@dataclass
class PostDraft:
    channel: str = ""
    content: str = ""
    best_post_time: str = ""
    hashtags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WeekPlan:
    week_label: str = ""
    posts: list[PostDraft] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "week_label": self.week_label,
            "posts": [p.to_dict() for p in self.posts],
        }


@dataclass
class SocialCalendar:
    month: str = ""
    weeks: list[WeekPlan] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "weeks": [w.to_dict() for w in self.weeks],
        }


_WEEK_CHANNEL_PATTERN = [
    "linkedin",
    "instagram",
    "linkedin",
    "instagram",
    "instagram",
]


class ContentCalendarGenerator:
    """Generates a SocialCalendar from active projects and PRBrief data.
    Pure Python — no LLM needed for the structural calendar layout."""

    DEFAULT_POST_TIMES = {
        "linkedin": ["07:30 IST", "12:00 IST", "17:00 IST"],
        "instagram": ["08:00 IST", "13:00 IST", "19:00 IST"],
    }
    DEFAULT_HASHTAGS = [
        "#BengaluruRealEstate",
        "#NorthBengaluru",
        "#LLS",
        "#RealEstateInvestment",
        "#Property",
    ]

    def generate(
        self,
        month: str,
        active_projects: list[str] | None = None,
        brief: PRBrief | None = None,
    ) -> SocialCalendar:
        weeks = []
        proj = active_projects or ["VEL"]
        for w in range(1, 5):
            posts = []
            for day_offset, channel in enumerate(_WEEK_CHANNEL_PATTERN):
                times = self.DEFAULT_POST_TIMES.get(channel, ["12:00 IST"])
                time_idx = min(w - 1, len(times) - 1)
                post_time = times[time_idx]
                post_content = _placeholder_content(channel, proj[0], brief)
                hashtags = list(self.DEFAULT_HASHTAGS) if channel == "instagram" else []
                posts.append(
                    PostDraft(
                        channel=channel,
                        content=post_content,
                        best_post_time=post_time,
                        hashtags=hashtags,
                    )
                )
            weeks.append(
                WeekPlan(
                    week_label=f"Week {w}",
                    posts=posts,
                )
            )
        return SocialCalendar(month=month, weeks=weeks)


def _placeholder_content(channel: str, project: str, brief: PRBrief | None) -> str:
    tagline = (
        brief.project_tagline
        if brief and brief.project_tagline
        else "Premium living, naturally."
    )
    if channel == "linkedin":
        return (
            f"{tagline} — {project} represents a new benchmark in North Bengaluru living. "
            "DM for a detailed project brief."
        )[:1300]
    return (f"{tagline} — {project}. Your sanctuary in North Bengaluru awaits.")[:2200]


class PostFormatter:
    """Formats post content per channel constraints.
    Ensures content never exceeds platform character limits."""

    LINKEDIN_MAX = 1300
    INSTAGRAM_MAX = 2200

    def format(self, content: str, channel: str) -> str:
        if channel == "linkedin":
            return content[: self.LINKEDIN_MAX]
        if channel == "instagram":
            return content[: self.INSTAGRAM_MAX]
        return content


def _log_agent_run(project: str, market: str, post_count: int, status: str) -> None:
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs (agent_id, market, event_type, status, records_inserted, notes)
                    VALUES ('social_media_agent', :m, 'calendar_generation', :s, :n, :notes)
                """),
                {
                    "m": market,
                    "s": status,
                    "n": post_count,
                    "notes": f"project={project}",
                },
            )
    except Exception as exc:
        logger.debug("[SocialMedia] Failed to log agent run: {}", exc)


class SocialMediaAgent:
    """Social Media Agent — produces weekly content calendar.
    Uses LIGHT LLM tier for content enrichment. Falls back to structured generation.
    Brand voice constraints match PR Head exactly.

    Never raises on LLM failure. Gracefully degrades to structured calendar.
    """

    _LLM_TIMEOUT_S = 45

    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature
        self._calendar_gen = ContentCalendarGenerator()
        self._formatter = PostFormatter()

    def _build_system_prompt(self) -> str:
        return (
            "You are the Social Media Manager for LLS (Lavish Life Styles), a premium "
            "real estate developer in North Bengaluru. You craft high-engagement social "
            "content that builds brand authority and drives inbound interest.\n\n"
            f"{LLS_BRAND_VOICE_CONSTRAINTS}\n\n"
            "Channel rules:\n"
            "- LinkedIn: Professional tone, no emoji, ≤1300 chars.\n"
            "- Instagram: Warm visual tone, ≤2200 chars + up to 30 relevant hashtags.\n"
            "Both channels: Every claim traceable to data. No puffery."
        )

    def _get_llm_with_fallback(self):
        if not _LLM_IMPORTED:
            raise ImportError("config.llm_router not available")
        try:
            return _get_light_llm(temperature=self.temperature)
        except Exception:
            logger.debug("[SocialMedia] Light LLM unavailable, trying analysis tier")
        try:
            return _get_analysis_llm(temperature=self.temperature)
        except Exception:
            logger.debug("[SocialMedia] Analysis LLM unavailable, trying heavy tier")
        try:
            from config.llm_router import get_heavy_llm

            return get_heavy_llm(temperature=self.temperature)
        except Exception:
            raise ImportError("No LLM tier available in config.llm_router")

    def _try_llm_enrichment(
        self,
        project_label: str,
        market: str,
        brief: PRBrief | None,
        cal: SocialCalendar,
    ) -> SocialCalendar:
        """Attempt LLM enrichment of calendar posts. Returns original on failure."""
        import concurrent.futures

        llm = self._get_llm_with_fallback()
        system_prompt = self._build_system_prompt()

        tagline = brief.project_tagline if brief and brief.project_tagline else ""
        narrative = (
            brief.investor_narrative[:300] if brief and brief.investor_narrative else ""
        )
        diffs = (
            brief.key_differentiators[:3] if brief and brief.key_differentiators else []
        )

        user_prompt = (
            f"Generate social media posts for {project_label} in {market}.\n"
            f"Tagline: {tagline}\n"
            f"Narrative: {narrative}\n"
            f"Differentiators: {', '.join(diffs)}\n\n"
            "Return a JSON dict with keys: linkedin_posts (list of 8 strings, each ≤1300 chars), "
            "instagram_posts (list of 12 strings, each ≤2200 chars with hashtags)."
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                llm.invoke,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            response = future.result(timeout=self._LLM_TIMEOUT_S)

        raw_text = ""
        if hasattr(response, "content"):
            raw_text = response.content
        elif isinstance(response, str):
            raw_text = response
        else:
            raw_text = str(response)

        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            try:
                start = raw_text.index("{")
                end = raw_text.rindex("}") + 1
                data = json.loads(raw_text[start:end])
            except (ValueError, json.JSONDecodeError):
                data = {}

        linkedin_posts = data.get("linkedin_posts", [])
        instagram_posts = data.get("instagram_posts", [])

        if linkedin_posts or instagram_posts:
            cal = self._merge_llm_posts(cal, linkedin_posts, instagram_posts)

        return cal

    def generate_week(
        self, project_label: str, market: str, brief: PRBrief | None = None
    ) -> SocialCalendar:
        """Generate a full month (4 weeks) of social media posts.

        Args:
            project_label: Short project identifier (e.g. 'VEL')
            market: Market name (Yelahanka/Devanahalli/Hebbal)
            brief: Optional PRBrief for rich content generation

        Returns:
            SocialCalendar with 4 weeks of daily posts
        """
        now = datetime.now(timezone.utc)
        month = now.strftime("%B %Y")

        cal = self._calendar_gen.generate(month, [project_label], brief)

        if _LLM_IMPORTED:
            try:
                cal = self._try_llm_enrichment(project_label, market, brief, cal)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "[SocialMedia] LLM timed out — using structured calendar"
                )
            except Exception as exc:
                logger.warning(
                    "[SocialMedia] LLM error: {} — using structured calendar", exc
                )

        post_count = sum(len(w.posts) for w in cal.weeks)
        logger.info(
            "[SocialMedia] Calendar generated for {}/{} — {} weeks, {} total posts",
            project_label,
            market,
            len(cal.weeks),
            post_count,
        )
        _log_agent_run(project_label, market, post_count, "success")
        return cal

    def _merge_llm_posts(
        self, cal: SocialCalendar, linkedin_posts: list[str], instagram_posts: list[str]
    ) -> SocialCalendar:
        li_iter = iter(linkedin_posts)
        ig_iter = iter(instagram_posts)

        for week in cal.weeks:
            for i, post in enumerate(week.posts):
                channel = _WEEK_CHANNEL_PATTERN[i % len(_WEEK_CHANNEL_PATTERN)]
                if channel == "linkedin":
                    content = next(li_iter, post.content)
                else:
                    content = next(ig_iter, post.content)
                post.content = self._formatter.format(content, channel)
        return cal

    def run(self, input_data: dict) -> dict:
        """Convenience entry — takes dict input, returns serialized calendar.
        Compatible with existing agent invocation pattern."""
        project_label = input_data.get("project_label", "VEL")
        market = input_data.get("market", "Yelahanka")
        brief_dict = input_data.get("pr_brief")

        brief = None
        if brief_dict:
            brief = PRBrief(
                project_tagline=brief_dict.get("project_tagline", ""),
                investor_narrative=brief_dict.get("investor_narrative", ""),
                key_differentiators=brief_dict.get("key_differentiators", []),
                target_segment=brief_dict.get("target_segment", ""),
                risk_acknowledgements=brief_dict.get("risk_acknowledgements", []),
            )

        cal = self.generate_week(project_label, market, brief)
        return {
            "status": "done",
            "calendar": cal.to_dict(),
            "post_count": sum(len(w.posts) for w in cal.weeks),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
