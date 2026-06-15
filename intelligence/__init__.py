"""
RE_OS — Intelligence Layer (Sprint 62–63)
==========================================
Composable market intelligence pipeline: 5 standalone modules + registry.

Modules:
    market_intel      MarketIntel.get_pulse(market)        → MarketPulse
    demand_intel      DemandIntel.get_signals(market)      → DemandSignals
    land_intel        LandIntel.get_land_picture(...)      → LandPicture
    legal_intel       LegalIntel.get_survey_picture(...)   → LegalPicture
    financial_intel   FinancialIntel.evaluate(...)         → FinancialEvaluation
    registry          IntelRegistry.get_full_picture(...)  → IntelPackage
"""

from intelligence.market_intel import MarketIntel, MarketPulse
from intelligence.demand_intel import DemandIntel, DemandSignals
from intelligence.land_intel import LandIntel, LandPicture
from intelligence.legal_intel import LegalIntel, LegalPicture
from intelligence.financial_intel import FinancialIntel, FinancialEvaluation
from intelligence.registry import IntelRegistry, IntelPackage

__all__ = [
    "MarketIntel",
    "MarketPulse",
    "DemandIntel",
    "DemandSignals",
    "LandIntel",
    "LandPicture",
    "LegalIntel",
    "LegalPicture",
    "FinancialIntel",
    "FinancialEvaluation",
    "IntelRegistry",
    "IntelPackage",
]
