"""
RE_OS — PR Head Agent (Sprint 53 — PR & Brand Department)
Role: brand narrative, positioning, investor story.
Uses ANALYSIS LLM tier (Cerebras/Groq). Enforces LLS brand voice.
"""

import json
import threading
from dataclasses import dataclass, field, asdict
from loguru import logger

from utils.pr_tools import market_positioning_tool

__all__ = ["PRBrief", "PRHeadAgent"]

_LLM_LOCK = threading.Lock()
_LLM_IMPORTED = False
try:
    from config.llm_router import (
        get_analysis_llm as _get_analysis_llm,
        get_light_llm as _get_light_llm,
    )

    _LLM_IMPORTED = True
except ImportError:
    logger.warning("[PRHead] config.llm_router not available — will use fallback only")


LLS_BRAND_VOICE_CONSTRAINTS = (
    "LLS brand voice — non-negotiable:\n"
    "1. Zero defect: Every claim must be sourced or caveated. No puffery.\n"
    "2. Nature as architecture: The project must integrate with the natural landscape, not impose on it.\n"
    "3. Timelines as commitments: Delivery dates are sacred. Missing a deadline is a brand failure.\n"
    "4. No hidden information: Risks are stated as clearly as strengths. Transparency is the brand.\n"
    "5. Home as sanctuary: Every unit must feel safe, private, and restorative."
)


@dataclass
class PRBrief:
    project_tagline: str = ""
    investor_narrative: str = ""
    key_differentiators: list[str] = field(default_factory=list)
    target_segment: str = ""
    risk_acknowledgements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PRHeadInput:
    market: str
    survey_no: str
    deal_type: str
    avg_psf: float
    psf_range: tuple[float, float]
    irr_scenarios: dict | None = None
    key_differentiators: list[str] | None = None
    competitor_grade_a_count: int = 0
    land_area_acres: float = 0.0
    total_units: int = 0

    def __post_init__(self):
        low = min(self.psf_range) if self.psf_range[0] or self.psf_range[1] else 0.0
        high = max(self.psf_range)
        object.__setattr__(self, "psf_range", (low, high))

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            market=str(data.get("market", "")),
            survey_no=str(data.get("survey_no", "")),
            deal_type=str(data.get("deal_type", "compare")),
            avg_psf=float(data.get("avg_psf", 0) or 0),
            psf_range=(
                float(data.get("psf_range_low", 0) or 0),
                float(data.get("psf_range_high", 0) or 0),
            ),
            irr_scenarios=data.get("irr_scenarios"),
            key_differentiators=data.get("key_differentiators"),
            competitor_grade_a_count=int(data.get("competitor_grade_a_count", 0) or 0),
            land_area_acres=float(data.get("land_area_acres", 0) or 0),
            total_units=int(data.get("total_units", 0) or 0),
        )


class PRHeadAgent:
    """PR Head Agent — produces a PRBrief from market intelligence data.

    Uses ANALYSIS LLM tier for narrative generation, with MarketPositioningTool
    for data-driven positioning. System prompt enforces LLS brand voice.
    Falls back through LIGHT → Ollama if ANALYSIS tier unavailable.
    """

    _LLM_TIMEOUT_S = 45

    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature

    def _build_system_prompt(self) -> str:
        return (
            "You are the PR Head for LLS (Lavish Life Styles), a premium real estate "
            "developer in North Bengaluru. Your role is to craft brand narrative, "
            "positioning, and investor stories that are compelling, honest, and "
            "strategically differentiated.\n\n"
            f"{LLS_BRAND_VOICE_CONSTRAINTS}\n\n"
            "You have access to a MarketPositioningTool that provides data-driven "
            "positioning statements based on market PSF and competitor analysis. "
            "Use it to ground your narrative in real market data.\n\n"
            "Your output must always be a structured PRBrief dataclass with:\n"
            "- project_tagline: ≤12 words, memorable, brand-forward\n"
            "- investor_narrative: 200-400 words — the 'why this project exists' story\n"
            "- key_differentiators: exactly 5 items — what separates this from Grade A competitors\n"
            "- target_segment: precise audience description\n"
            "- risk_acknowledgements: 2-3 honest risk statements — LLS requires transparency"
        )

    def _build_prompt(self, inp: PRHeadInput, positioning_stmt: str) -> str:
        diffs = inp.key_differentiators or []
        diffs_str = (
            "\n".join(f"  - {d}" for d in diffs) if diffs else "  - (not specified)"
        )

        irr_str = ""
        if inp.irr_scenarios:
            irr_parts = []
            for k, v in inp.irr_scenarios.items():
                try:
                    irr_parts.append(f"  - {k}: {float(v):.1f}%")
                except (ValueError, TypeError):
                    irr_parts.append(f"  - {k}: {v}")
            irr_str = "\n".join(irr_parts)

        return (
            f"Generate a PRBrief for the following deal:\n\n"
            f"Market: {inp.market}\n"
            f"Survey No: {inp.survey_no}\n"
            f"Deal Type: {inp.deal_type}\n"
            f"Average PSF: ₹{inp.avg_psf:,.0f}\n"
            f"PSF Range: ₹{inp.psf_range[0]:,.0f} – ₹{inp.psf_range[1]:,.0f}\n"
            f"Land Area: {inp.land_area_acres:.2f} acres ({inp.total_units} units)\n\n"
            f"IRR Scenarios:\n{irr_str if irr_str else '  - (not provided)'}\n\n"
            f"Key Differentiators:\n{diffs_str}\n\n"
            f"MarketPositioningTool says:\n{positioning_stmt}\n\n"
            "Return the PRBrief as a structured JSON dict with keys: "
            "project_tagline, investor_narrative, key_differentiators (list of 5), "
            "target_segment, risk_acknowledgements (list of 2-3)."
        )

    def _get_llm_with_fallback(self):
        """Return ANALYSIS tier LLM, falling back to LIGHT then Ollama."""
        if not _LLM_IMPORTED:
            raise ImportError("config.llm_router not available")
        try:
            return _get_analysis_llm(temperature=self.temperature)
        except Exception:
            logger.debug("[PRHead] Analysis LLM unavailable, trying light tier")
        try:
            return _get_light_llm(temperature=self.temperature)
        except Exception:
            logger.debug("[PRHead] Light LLM unavailable, trying heavy tier")
        from config.llm_router import get_heavy_llm

        return get_heavy_llm(temperature=self.temperature)

    def _parse_llm_response(self, raw: str) -> PRBrief:
        """Parse LLM response into PRBrief. Falls back to defaults on error."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            try:
                start = raw.index("{")
                end = raw.rindex("}") + 1
                data = json.loads(raw[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.warning(
                    "[PRHead] Failed to parse LLM output as JSON, using fallback"
                )
                return self._fallback_brief()

        return PRBrief(
            project_tagline=str(data.get("project_tagline", ""))[:120],
            investor_narrative=str(data.get("investor_narrative", "")),
            key_differentiators=list(data.get("key_differentiators", []))[:5],
            target_segment=str(data.get("target_segment", "")),
            risk_acknowledgements=list(data.get("risk_acknowledgements", []))[:3],
        )

    def _fallback_brief(self) -> PRBrief:
        return PRBrief(
            project_tagline="Premium living, naturally.",
            investor_narrative=(
                "This project represents a strategically located land parcel in North Bengaluru's "
                "fastest-growing corridor. With proximity to the international airport, proposed "
                "metro extension, and the STRR, the location offers strong capital appreciation "
                "potential. LLS brings its signature zero-defect construction philosophy and "
                "nature-integrated design approach."
            ),
            key_differentiators=[
                "Zero-defect construction quality with third-party audits",
                "Nature-integrated architecture preserving existing topography",
                "On-time delivery track record with penalty clauses",
                "Transparent pricing with no hidden charges",
                "Post-possession community management program",
            ],
            target_segment="Premium home buyers and long-term investors in the ₹80L–₹2Cr bracket",
            risk_acknowledgements=[
                "Infrastructure timelines (metro, STRR) depend on government execution",
                "Market absorption rate may slow if multiple large launches coincide",
                "Construction cost inflation could pressure margins if prolonged",
            ],
        )

    def run(self, input_data: dict) -> PRBrief:
        """Execute PR Head Agent.

        Args:
            input_data: Dict with market, survey_no, deal_type, avg_psf, psf_range_low,
                       psf_range_high, irr_scenarios, key_differentiators,
                       competitor_grade_a_count, land_area_acres, total_units

        Returns:
            PRBrief dataclass with narrative, tagline, differentiators, etc.
        """
        inp = PRHeadInput.from_dict(input_data)

        positioning_stmt = market_positioning_tool(
            market=inp.market,
            avg_psf=inp.avg_psf,
            competitor_psf_range=inp.psf_range,
            grade_a_count=inp.competitor_grade_a_count,
        )

        if not _LLM_IMPORTED:
            logger.warning("[PRHead] LLM router unavailable — using fallback brief")
            return self._fallback_brief()

        try:
            llm = self._get_llm_with_fallback()
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_prompt(inp, positioning_stmt)

            import concurrent.futures

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

            brief = self._parse_llm_response(raw_text)
            logger.info(
                "[PRHead] Brief generated for %s/%s — tagline: %s",
                inp.market,
                inp.survey_no,
                brief.project_tagline,
            )
            return brief

        except concurrent.futures.TimeoutError:
            logger.warning(
                "[PRHead] LLM call timed out after %ds — using fallback",
                self._LLM_TIMEOUT_S,
            )
            return self._fallback_brief()
        except (ImportError, ConnectionError, OSError, ValueError) as exc:
            logger.warning("[PRHead] LLM call failed: %s — using fallback brief", exc)
            return self._fallback_brief()
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            logger.warning("[PRHead] Unexpected LLM error: %s — using fallback", exc)
            return self._fallback_brief()
