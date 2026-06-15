"""
Validation tests for the Renderer Agent's ImageBriefGeneratorTool.
Covers: happy path, all three PSF bands, edge cases (invalid JSON, empty unit_mix).
"""

import json
import pytest

pytestmark = pytest.mark.unit


def test_image_brief_generator_produces_midjourney_prompt():
    from agents.renderer_agent import ImageBriefGeneratorTool

    tool = ImageBriefGeneratorTool()
    result = tool._run(
        json.dumps(
            {
                "project_type": "residential",
                "location": "Yelahanka",
                "psf_band": "mid-range",
                "unit_mix": {"1bhk": 15, "2bhk": 55, "3bhk": 30},
                "floors": 12,
                "green_pct": 45.0,
            }
        )
    )
    parsed = json.loads(result)

    assert "prompt" in parsed
    assert "--ar 16:9" in parsed["prompt"], "Missing Midjourney aspect ratio flag"
    assert "--v 6" in parsed["prompt"], "Missing Midjourney version flag"
    assert parsed.get("location") == "Yelahanka"
    assert "style_preset" in parsed


def test_invalid_json_returns_error_dict():
    from agents.renderer_agent import ImageBriefGeneratorTool

    tool = ImageBriefGeneratorTool()
    result = tool._run("not valid json {{{")
    parsed = json.loads(result)
    assert "error" in parsed


def test_unknown_psf_band_falls_back_to_mid_range():
    from agents.renderer_agent import ImageBriefGeneratorTool

    tool = ImageBriefGeneratorTool()
    result = tool._run(
        json.dumps(
            {
                "project_type": "residential",
                "location": "Devanahalli",
                "psf_band": "super-luxury-unknown",
                "unit_mix": {"3bhk": 100},
                "floors": 8,
                "green_pct": 30.0,
            }
        )
    )
    parsed = json.loads(result)
    assert "prompt" in parsed
    assert "--ar 16:9" in parsed["prompt"]


def test_premium_psf_band_uses_premium_style():
    from agents.renderer_agent import ImageBriefGeneratorTool

    tool = ImageBriefGeneratorTool()
    result = tool._run(
        json.dumps(
            {
                "project_type": "residential",
                "location": "Hebbal",
                "psf_band": "premium",
                "unit_mix": {"3bhk": 60, "4bhk": 40},
                "floors": 20,
                "green_pct": 35.0,
            }
        )
    )
    parsed = json.loads(result)
    assert parsed.get("style_preset") == "premium"
    assert (
        "luxury" in parsed["prompt"].lower() or "infinity" in parsed["prompt"].lower()
    )


def test_empty_unit_mix_does_not_crash():
    from agents.renderer_agent import ImageBriefGeneratorTool

    tool = ImageBriefGeneratorTool()
    result = tool._run(
        json.dumps(
            {
                "project_type": "residential",
                "location": "Yelahanka",
                "psf_band": "affordable",
                "unit_mix": {},
                "floors": 5,
                "green_pct": 20.0,
            }
        )
    )
    parsed = json.loads(result)
    assert "prompt" in parsed
    assert "--ar 16:9" in parsed["prompt"]
