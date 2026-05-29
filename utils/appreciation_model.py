"""
RE_OS — Appreciation Forecasting Model
--------------------------------------
Predicts PSF trajectory based on infrastructure deployment schedules.
Phase 2 foundation for making RE_OS predictive, not just descriptive.
"""

import csv
import json
from pathlib import Path
from datetime import datetime

_PINCODE_CSV_PATH = Path(__file__).parent.parent / "data" / "bangalore_pincode_master.csv"
_INFRA_JSON_PATH = Path(__file__).parent.parent / "data" / "bangalore_infrastructure_timeline.json"

_BASE_APPRECIATION_RATES = {
    "Urban_Core_Apex": 0.03,
    "Urban_Core_High_Value": 0.05,
    "Urban_Core": 0.04,
    "Peri_Urban_High_Value": 0.12,
    "Peri_Urban_Transition": 0.08,
    "Peripheral_Urban": 0.08,
    "Peripheral_Urban_High_Value": 0.10,
    "Rural_Speculative": 0.04,
    "Rural_Industrial_Fringe": 0.04,
    "Peri_Urban_Industrial": 0.06,
    "Industrial_Zone": 0.05,
    "Peripheral_High_Value": 0.09,
    "Peri_Urban_Tech": 0.07,
    "Tier1_Industrial_Growth": 0.08,
    "Peripheral_Rural": 0.03,
}

_WATER_RISK_PENALTY = {
    "Very_High": -0.08,
    "High": -0.04,
    "Medium": 0.0,
    "Medium_High": 0.0,
    "Low": 0.02,
    "Low_Medium": 0.0,
}


def _load_pincode_data():
    pincodes = {}
    with open(_PINCODE_CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pincodes[row["pincode"]] = row
    return pincodes


def _load_infrastructure_data():
    with open(_INFRA_JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("projects", [])


_PINCODE_DATA = None
_INFRA_DATA = None


def _get_pincode_data():
    global _PINCODE_DATA
    if _PINCODE_DATA is None:
        _PINCODE_DATA = _load_pincode_data()
    return _PINCODE_DATA


def _get_infra_data():
    global _INFRA_DATA
    if _INFRA_DATA is None:
        _INFRA_DATA = _load_infrastructure_data()
    return _INFRA_DATA


def _get_infrastructure_events(pincode: str) -> list:
    events = []
    pincode_str = str(pincode)
    for project in _get_infra_data():
        if pincode_str in project.get("influenced_pincodes", []):
            events.append({
                "project": project.get("name", ""),
                "status": project.get("status", ""),
                "completion_date": project.get("completion_date", ""),
                "psf_impact_on_completion_pct": project.get("psf_appreciation_on_completion_pct", 0),
                "psf_appreciation_5yr_pct": project.get("psf_appreciation_5yr_pct", 0),
                "psf_appreciation_10yr_pct": project.get("psf_appreciation_10yr_pct", 0),
                "probability": project.get("completion_probability", 1.0),
            })
    return events


def get_appreciation_forecast(pincode: str) -> dict:
    """
    Returns a structured appreciation forecast for a given pincode.

    Returns:
    {
        "pincode": "562114",
        "area": "Hoskote Town",
        "current_psf_min": 0,
        "current_psf_max": 0,
        "current_land_cr_per_acre_min": 1.0,
        "current_land_cr_per_acre_max": 2.5,
        "investment_tier": "Tier1_Industrial_Growth",
        "water_risk": "Medium",
        "infrastructure_events": [...],
        "forecast": {
            "3yr_appreciation_pct": 45,
            "5yr_appreciation_pct": 80,
            "10yr_appreciation_pct": 150,
            "confidence": "medium",
            "primary_driver": "STRR Node operational + NH-4 logistics hub"
        },
        "recommendation": "Strong Buy — logistics land banking window closing",
        "risks": [...]
    }
    """
    pincode_str = str(pincode).strip()
    pin_data = _get_pincode_data().get(pincode_str, {})

    area = pin_data.get("area_name", "Unknown")
    zone_type = pin_data.get("zone_type", "Rural_Speculative")
    water_risk = pin_data.get("water_risk_level", "Medium")
    investment_tier = pin_data.get("investment_tier", "Tier3_Speculative")

    current_psf_min = float(pin_data.get("apt_psf_min", 0) or 0)
    current_psf_max = float(pin_data.get("apt_psf_max", 0) or 0)
    current_land_min = float(pin_data.get("land_cr_per_acre_min", 0) or 0)
    current_land_max = float(pin_data.get("land_cr_per_acre_max", 0) or 0)

    infrastructure_events = _get_infrastructure_events(pincode_str)

    base_rate = _BASE_APPRECIATION_RATES.get(zone_type, 0.05)
    water_penalty = _WATER_RISK_PENALTY.get(water_risk, 0.0)

    infra_3yr_boost = 0.0
    infra_5yr_boost = 0.0
    infra_10yr_boost = 0.0
    primary_drivers = []

    for event in infrastructure_events:
        status = event.get("status", "")
        prob = event.get("probability", 1.0)

        if status == "functional":
            impact = event.get("psf_impact_on_completion_pct", 0)
            infra_3yr_boost += impact * 0.6 / 100 * prob
            infra_5yr_boost += impact * 0.6 / 100 * prob
            infra_10yr_boost += impact / 100 * prob
            primary_drivers.append(event.get("project", ""))
        elif status == "under_construction":
            impact = event.get("psf_appreciation_on_completion_pct", 0)
            infra_5yr_boost += impact / 100 * prob
            infra_10yr_boost += impact / 100 * prob
        elif status == "planned":
            impact_5yr = event.get("psf_appreciation_5yr_pct", 0) * prob / 100
            impact_10yr = event.get("psf_appreciation_10yr_pct", 0) * prob / 100
            infra_5yr_boost += impact_5yr * 0.7
            infra_10yr_boost += impact_10yr * 0.8

    if infrastructure_events and any(e.get("status") == "functional" for e in infrastructure_events):
        confidence = "high"
    elif infrastructure_events:
        confidence = "medium"
    else:
        confidence = "low"

    forecast_3yr = round((base_rate * 3 + water_penalty * 3 + infra_3yr_boost * 100), 1)
    forecast_5yr = round((base_rate * 5 + water_penalty * 5 + infra_5yr_boost * 100), 1)
    forecast_10yr = round((base_rate * 10 + water_penalty * 10 + infra_10yr_boost * 100), 1)

    primary_driver = primary_drivers[0] if primary_drivers else "Base market appreciation"

    tier_recs = {
        "Tier1_Apex_Growth": "Strong Buy — premium location appreciation accelerating",
        "Tier1_High_Growth": "Strong Buy — high growth corridor",
        "Tier1_Premium": "Buy — premium location with steady appreciation",
        "Tier1_Industrial_Growth": "Strong Buy — logistics land banking window closing",
        "Tier2_Stable": "Hold — stable growth trajectory",
        "Tier2_Improving": "Accumulate — improving fundamentals",
        "Tier3_Slow": "Watch — limited appreciation expected",
        "Tier3_Speculative": "Wait — speculative play, verify infrastructure timing",
    }
    recommendation = tier_recs.get(investment_tier, "Monitor — verify fundamentals")

    risks = []
    if water_risk in ("Very_High", "High", "Medium"):
        risks.append("Water risk impacts long-term viability")
    if any(e.get("status") == "planned" for e in infrastructure_events):
        risks.append("Planned infrastructure subject to delays")

    return {
        "pincode": pincode_str,
        "area": area,
        "current_psf_min": current_psf_min,
        "current_psf_max": current_psf_max,
        "current_land_cr_per_acre_min": current_land_min,
        "current_land_cr_per_acre_max": current_land_max,
        "investment_tier": investment_tier,
        "water_risk": water_risk,
        "infrastructure_events": infrastructure_events,
        "forecast": {
            "3yr_appreciation_pct": forecast_3yr,
            "5yr_appreciation_pct": forecast_5yr,
            "10yr_appreciation_pct": forecast_10yr,
            "confidence": confidence,
            "primary_driver": primary_driver,
        },
        "recommendation": recommendation,
        "risks": risks,
    }


def get_pincodes_for_market(market_name: str) -> list:
    """Return list of pincodes associated with a market name."""
    pincodes = []
    market_lower = market_name.lower()
    for pincode, data in _get_pincode_data().items():
        if market_lower in data.get("micro_market", "").lower():
            pincodes.append(pincode)
    return pincodes