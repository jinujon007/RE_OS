"""
tasks.py

Defines RQ job functions for the RE_OS system.
"""

from crews.market_intel_crew import run_market_intelligence

def run_market_intelligence_job(market: str) -> str:
    """
    RQ job that runs the market intelligence crew for a given market.

    Parameters
    ----------
    market : str
        The market name to run the crew for.

    Returns
    -------
    str
        The report body returned by run_market_intelligence.
    """
    return run_market_intelligence(market)