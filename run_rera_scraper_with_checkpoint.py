#!/usr/bin/env python3
"""
Script to run RERA scraper via the agent tool to ensure checkpoint is saved.
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.scraper_agent import RERAScraperTool

def scrape_market_with_checkpoint(market_name):
    """Scrape a market and save checkpoint via the agent tool."""
    print(f"Scraping {market_name} via agent tool (with checkpoint saving)...")
    tool = RERAScraperTool()
    result = tool._run(market_name)
    
    # Parse the result to get project count
    import json
    projects = json.loads(result)
    live_count = len([p for p in projects if p.get("source") == "rera_karnataka_live"])
    
    print(f"  Found {len(projects)} total projects")
    print(f"  Live data: {live_count} projects")
    print(f"  Fallback: {len(projects) - live_count} projects")
    
    return live_count

if __name__ == "__main__":
    markets = ["Yelahanka", "Hebbal"]
    results = {}
    
    for market in markets:
        try:
            live_count = scrape_market_with_checkpoint(market)
            results[market] = live_count
            print(f"✓ {market}: {live_count} live projects\n")
        except Exception as e:
            print(f"✗ {market}: Failed with error: {e}\n")
            results[market] = 0
    
    # Check if we meet the success criteria (≥50 live projects for Yelahanka OR Hebbal)
    yelahanka_count = results.get("Yelahanka", 0)
    hebbal_count = results.get("Hebbal", 0)
    
    if yelahanka_count >= 50 or hebbal_count >= 50:
        print("SUCCESS: At least one market has ≥50 live RERA projects")
        print(f"  Yelahanka: {yelahanka_count}")
        print(f"  Hebbal: {hebbal_count}")
    else:
        print("FAILURE: Neither market has ≥50 live RERA projects")
        print(f"  Yelahanka: {yelahanka_count}")
        print(f"  Hebbal: {hebbal_count}")
        sys.exit(1)