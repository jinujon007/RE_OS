"""Tests for PR Head Agent (Sprint 53 — PR & Brand Department)."""
import pytest
from dataclasses import fields

pytestmark = pytest.mark.unit


class TestPRBriefDataclass:

    def test_pr_head_returns_prbrief_dataclass(self):
        from agents.pr_head_agent import PRBrief
        brief = PRBrief(
            project_tagline="Test tagline",
            investor_narrative="Test narrative",
            key_differentiators=["a", "b", "c", "d", "e"],
            target_segment="Test segment",
            risk_acknowledgements=["risk1", "risk2"],
        )
        assert isinstance(brief, PRBrief)
        assert hasattr(brief, "project_tagline")
        assert hasattr(brief, "investor_narrative")
        assert hasattr(brief, "key_differentiators")
        assert hasattr(brief, "target_segment")
        assert hasattr(brief, "risk_acknowledgements")
        assert len(fields(PRBrief)) == 5

    def test_project_tagline_under_12_words(self):
        from agents.pr_head_agent import PRBrief
        taglines = [
            "Zero defect. On time. Naturally.",
            "Premium living, naturally.",
            "Home as sanctuary.",
            "Where nature meets architecture.",
            "Timelines as commitments. Quality as gospel.",
        ]
        for t in taglines:
            brief = PRBrief(project_tagline=t)
            word_count = len(brief.project_tagline.split())
            assert word_count <= 12, f"Tagline '{t}' has {word_count} words (max 12)"

    def test_key_differentiators_has_5_items(self):
        from agents.pr_head_agent import PRHeadAgent
        agent = PRHeadAgent()
        brief = agent._fallback_brief()
        assert len(brief.key_differentiators) == 5

    def test_brand_voice_constraint_in_system_prompt(self):
        from agents.pr_head_agent import LLS_BRAND_VOICE_CONSTRAINTS
        constraints = ["zero defect", "nature as architecture", "home as sanctuary",
                       "no hidden information", "timelines as commitments"]
        lower = LLS_BRAND_VOICE_CONSTRAINTS.lower()
        for c in constraints:
            assert c in lower, f"Missing brand voice constraint: {c}"

    def test_market_positioning_tool_value_market(self):
        from utils.pr_tools import market_positioning_tool
        stmt = market_positioning_tool("Yelahanka", 7200, (9000, 11000), 4)
        assert "Yelahanka" in stmt
        assert "VALUE" in stmt.upper()

    def test_market_positioning_tool_premium_market(self):
        from utils.pr_tools import market_positioning_tool
        stmt = market_positioning_tool("Hebbal", 12500, (9000, 11000), 3)
        assert "Hebbal" in stmt
        assert "PREMIUM" in stmt.upper()

    def test_market_positioning_tool_no_competitors(self):
        from utils.pr_tools import market_positioning_tool
        stmt = market_positioning_tool("Devanahalli", 6000, (0, 0), 0)
        assert "Devanahalli" in stmt
        assert "emerging" in stmt.lower()

    def test_pr_head_input_from_dict(self):
        from agents.pr_head_agent import PRHeadInput
        inp = PRHeadInput.from_dict({
            "market": "Yelahanka",
            "survey_no": "45/2",
            "deal_type": "jd",
            "avg_psf": 7200,
            "psf_range_low": 6000,
            "psf_range_high": 12000,
        })
        assert inp.market == "Yelahanka"
        assert inp.avg_psf == 7200.0
        assert inp.psf_range == (6000.0, 12000.0)

    def test_psf_range_sorted_automatically(self):
        """C3 fix: psf_range tuple is auto-sorted (low, high)."""
        from agents.pr_head_agent import PRHeadInput
        inp = PRHeadInput.from_dict({
            "market": "Yelahanka",
            "survey_no": "45/2",
            "deal_type": "compare",
            "avg_psf": 8000,
            "psf_range_low": 12000,
            "psf_range_high": 6000,
        })
        assert inp.psf_range[0] <= inp.psf_range[1], "psf_range should be sorted low→high"

    def test_pr_head_run_returns_fallback_when_llm_unavailable(self):
        """Tests fallback brief when LLM router is not importable."""
        from agents.pr_head_agent import PRHeadAgent
        agent = PRHeadAgent()
        brief = agent._fallback_brief()
        assert brief.project_tagline
        assert len(brief.key_differentiators) == 5
        assert len(brief.risk_acknowledgements) >= 2

    def test_pr_head_input_empty_values_default_safely(self):
        """Empty/missing input values default to safe values."""
        from agents.pr_head_agent import PRHeadInput
        inp = PRHeadInput.from_dict({})
        assert inp.market == ""
        assert inp.avg_psf == 0.0
        assert inp.psf_range == (0.0, 0.0)
        assert inp.competitor_grade_a_count == 0

    def test_positioning_tool_boundary_conditions(self):
        """Edge cases: zero PSF, negative values, very high values."""
        from utils.pr_tools import market_positioning_tool
        stmt = market_positioning_tool("Yelahanka", 0, (9000, 11000), 4)
        assert "VALUE" in stmt.upper() or "emerging" in stmt.lower()
        stmt2 = market_positioning_tool("Hebbal", 99999, (10000, 12000), 2)
        assert "PREMIUM" in stmt2.upper()

    def test_word_boundary_truncate_never_splits_words(self):
        """Truncation algorithm preserves word boundaries."""
        from agents.content_writer_agent import _word_boundary_truncate
        text = "This is a long sentence that must be truncated at word boundary."
        result = _word_boundary_truncate(text, 30, " ...")
        assert result.endswith(" ...")
        # The truncated part should end with a complete word, not mid-word
        truncated = result[:-4]
        assert text.startswith(truncated) or truncated.rfind(" ") > 0
        assert len(result) <= 33  # 30 + len(" ...")
