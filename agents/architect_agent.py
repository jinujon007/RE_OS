import json
from crewai.tools import BaseTool
from crewai import Agent
from config.llm_router import get_analysis_llm
from utils.fsi_calculator import calculate_fsi, recommend_unit_mix
from utils.green_coverage import calculate_green_coverage


class FSICalculatorTool(BaseTool):
    name: str = "fsi_calculator"
    description: str = (
        "Calculate buildable area, sellable area, max floors, and plot coverage "
        "for a land parcel. Input: JSON with 'land_area_sqft' (float), "
        "'zone' (R1/R2/C1, default R2), 'efficiency' (0.5–0.75, default 0.65), "
        "'market' (Yelahanka/Devanahalli/Hebbal, optional — uses market-specific FAR rules). "
        "Returns FSI result as JSON."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            result = calculate_fsi(
                land_area_sqft=float(params.get("land_area_sqft", 0)),
                zone=str(params.get("zone", "R2")),
                efficiency=float(params.get("efficiency", 0.65)),
                market=params.get("market") or None,
            )
            return json.dumps(
                {
                    "zone": result.zone,
                    "land_area_sqft": result.land_area_sqft,
                    "buildable_area_sqft": result.buildable_area_sqft,
                    "sellable_area_sqft": result.sellable_area_sqft,
                    "max_floors": result.max_floors,
                    "far": result.far,
                    "plot_coverage_pct": round(result.plot_coverage * 100),
                    "setback_front_m": result.setback_front_m,
                    "setback_side_m": result.setback_side_m,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})


class TypologyRecommenderTool(BaseTool):
    name: str = "typology_recommender"
    description: str = (
        "Recommend unit mix (1BHK/2BHK/3BHK split) for a market PSF band. "
        "Input: JSON with 'avg_listing_psf' (float). "
        "Returns unit mix percentages and average carpet area recommendation."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            result = recommend_unit_mix(float(params.get("avg_listing_psf", 5000)))
            return json.dumps(
                {
                    "psf_band": result.psf_band,
                    "unit_mix": {
                        "1bhk_pct": result.bhk_1_pct,
                        "2bhk_pct": result.bhk_2_pct,
                        "3bhk_pct": result.bhk_3_pct,
                    },
                    "recommended_avg_carpet_sqft": result.recommended_avg_carpet_sqft,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})


class GreenCoverageTool(BaseTool):
    name: str = "green_coverage"
    description: str = (
        "Calculate landscape area, tree count, and BDA green coverage compliance. "
        "Input: JSON with 'land_area_sqft' (float), 'built_coverage_pct' (0.0–1.0, "
        "use plot_coverage from fsi_calculator result). "
        "Returns landscape sqft, green %, tree count, BDA compliance flag."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            result = calculate_green_coverage(
                land_area_sqft=float(params.get("land_area_sqft", 0)),
                built_coverage_pct=float(params.get("built_coverage_pct", 0.55)),
            )
            return json.dumps(
                {
                    "land_area_sqft": result.land_area_sqft,
                    "landscape_area_sqft": result.landscape_area_sqft,
                    "green_pct": result.green_pct,
                    "tree_count": result.tree_count,
                    "meets_bda_minimum": result.meets_bda_minimum,
                    "bda_minimum_pct": 15.0,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})


def create_architect_agent() -> Agent:
    return Agent(
        role="Principal Architect — Engineering Division",
        goal=(
            "Given land area, zone, and market PSF, produce a buildable typology: "
            "FSI analysis, unit mix, floor count, setback compliance summary, "
            "and green coverage compliance (BDA minimum 15%)."
        ),
        backstory=(
            "Senior architect with 15 years designing residential projects across North Bengaluru. "
            "Understands BDA master plan zones, FAR constraints, RERA unit-mix requirements, "
            "BDA green coverage minimums (15%), "
            "and how to squeeze maximum sellable area from a site without violating setbacks. "
            "Starts every analysis from first principles: land area -> buildable area -> sellable area -> unit mix. "
            "Output is always a structured brief Jinu can hand directly to a structural engineer."
        ),
        tools=[FSICalculatorTool(), TypologyRecommenderTool(), GreenCoverageTool()],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


if __name__ == "__main__":
    agent = create_architect_agent()
    print(f"Architect Agent created: {agent.role}")
    print(f"Tools: {[t.name for t in agent.tools]}")

    r = calculate_fsi(12000, "R2")
    m = recommend_unit_mix(6500)
    g = calculate_green_coverage(12000, r.plot_coverage)
    print("\nTest FSI (12,000 sqft, R2):")
    print(f"  Buildable: {r.buildable_area_sqft:,.0f} sqft")
    print(f"  Sellable:  {r.sellable_area_sqft:,.0f} sqft")
    print(f"  Max floors: {r.max_floors}")
    print(
        f"  Unit mix: {m.bhk_1_pct}% 1BHK / {m.bhk_2_pct}% 2BHK / {m.bhk_3_pct}% 3BHK"
    )
    print(
        f"  Green coverage: {g.green_pct}% | Trees: {g.tree_count} | BDA min met: {g.meets_bda_minimum}"
    )
