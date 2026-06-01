"""
RE_OS — Renderer Agent (Phase 5 — Engineering / Creative Division)
Given a typology brief, outputs a Midjourney/DALL-E image prompt.
"""
import json
from crewai.tools import BaseTool
from crewai import Agent
from config.llm_router import get_analysis_llm

_STYLE_PRESETS = {
    "affordable": "warm earth tones, functional landscaping, community spaces, practical amenities",
    "mid-range":  "contemporary architecture, landscaped podiums, rooftop gardens, natural light focus",
    "premium":    "luxury finishes, infinity pool, sky terraces, dense tropical greenery, dramatic lighting",
}

_LOCATION_CONTEXT = {
    "Yelahanka":    "North Bengaluru suburbs, Nandi Hills backdrop, open sky, green corridor",
    "Devanahalli":  "airport corridor, wide roads, emerging skyline, farmland contrast",
    "Hebbal":       "lakeside, Bengaluru urban fringe, elevated site with city views",
}


class ImageBriefGeneratorTool(BaseTool):
    name: str = "image_brief_generator"
    description: str = (
        "Generate a Midjourney/DALL-E image prompt from a project typology brief. "
        "Input: JSON with 'project_type' (residential/mixed), 'location' (market name), "
        "'psf_band' (affordable/mid-range/premium), 'unit_mix' (dict with 1bhk/2bhk/3bhk pct), "
        "'floors' (int), 'green_pct' (float), 'style_keywords' (optional list). "
        "Returns a prompt string ready for Midjourney v6."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            project_type = params.get("project_type", "residential")
            location = params.get("location", "Bengaluru")
            psf_band = params.get("psf_band", "mid-range")
            unit_mix = params.get("unit_mix", {})
            floors = int(params.get("floors", 10))
            green_pct = float(params.get("green_pct", 40.0))
            extra_keywords = params.get("style_keywords", [])

            dominant_unit = max(unit_mix, key=unit_mix.get) if unit_mix else "2bhk"
            style = _STYLE_PRESETS.get(psf_band, _STYLE_PRESETS["mid-range"])
            loc_ctx = _LOCATION_CONTEXT.get(location, "Bengaluru suburban setting")
            extra = ", ".join(extra_keywords) if extra_keywords else ""
            extra_part = f"{extra[0].upper() + extra[1:]}. " if extra else ""

            prompt = (
                f"Architectural render of a {floors}-floor {project_type} tower in {location}, India. "
                f"{loc_ctx}. Dominant unit type: {dominant_unit.upper()}. "
                f"{round(green_pct)}% site coverage in mature tropical landscaping, podium garden. "
                f"{style[0].upper() + style[1:]}. "
                f"{extra_part}"
                f"Professional architectural visualization, golden hour lighting, "
                f"8k render, photorealistic, Bengaluru real estate marketing style. "
                f"--ar 16:9 --v 6"
            )
            return json.dumps({"prompt": prompt, "style_preset": psf_band, "location": location}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})


def create_renderer_agent() -> Agent:
    return Agent(
        role="Creative Renderer — Engineering Division",
        goal=(
            "Given an architectural typology brief, generate a detailed image prompt "
            "for Midjourney or DALL-E that captures the project's character, location, "
            "and product positioning."
        ),
        backstory=(
            "Visual storyteller with deep knowledge of Bengaluru residential architecture. "
            "Translates FSI math and unit mix tables into imagery that sells the lifestyle, "
            "not just the square footage. Understands how North Bengaluru's micro-climates, "
            "topography, and neighbourhood character should shape a project's visual identity. "
            "Every prompt is specific enough to produce a usable render on the first try."
        ),
        tools=[ImageBriefGeneratorTool()],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=2,
    )


if __name__ == "__main__":
    tool = ImageBriefGeneratorTool()
    result = tool._run(json.dumps({
        "project_type": "residential",
        "location": "Yelahanka",
        "psf_band": "mid-range",
        "unit_mix": {"1bhk": 15, "2bhk": 55, "3bhk": 30},
        "floors": 12,
        "green_pct": 45.0,
    }))
    print(json.loads(result)["prompt"])
