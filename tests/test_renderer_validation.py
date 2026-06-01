"""
Validation test for the Renderer Agent's ImageBriefGeneratorTool.
Confirms the Midjourney prompt output format (--ar 16:9 --v 6 suffix).
"""

import json
import pytest

pytestmark = pytest.mark.unit


def test_image_brief_generator_produces_midjourney_prompt():
    from agents.renderer_agent import ImageBriefGeneratorTool

    tool = ImageBriefGeneratorTool()
    result = tool._run(json.dumps({
        "project_type": "residential",
        "location": "Yelahanka",
        "psf_band": "mid-range",
        "unit_mix": {"1bhk": 15, "2bhk": 55, "3bhk": 30},
        "floors": 12,
        "green_pct": 45.0,
    }))
    parsed = json.loads(result)

    assert "prompt" in parsed
    assert "--ar 16:9" in parsed["prompt"], "Missing Midjourney aspect ratio flag"
    assert "--v 6" in parsed["prompt"], "Missing Midjourney version flag"
    assert parsed.get("location") == "Yelahanka"
    assert "style_preset" in parsed
