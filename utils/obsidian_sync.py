"""
RE_OS — Obsidian Sync Utility
Handles synchronization of market briefs to Obsidian vault
"""

import os
import json
from datetime import datetime
from pathlib import Path
from config.settings import OBSIDIAN_VAULT_PATH


def sync_to_obsidian(market: str, synthesis_text: str) -> bool:
    """
    Sync market brief to Obsidian vault
    
    Args:
        market: Market name (e.g., 'Yelahanka')
        synthesis_text: CEO synthesis text to write
        
    Returns:
        bool: True if sync successful, False otherwise
    """
    try:
        # Target path: D:\Brain\JINU JOSHI\03 LLS\01 Wiki\markets\{market}.md
        vault_path = Path(OBSIDIAN_VAULT_PATH)
        market_file = vault_path / "markets" / f"{market}.md"
        
        # Ensure markets directory exists
        market_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate frontmatter
        frontmatter = {
            "type": "wiki",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "area": "lls",
            "market": market,
            "confidence": 0.8,  # Default confidence for AI-generated content
            "ai_generated": True
        }
        
        # Create markdown content
        markdown_content = f"---\n"
        for key, value in frontmatter.items():
            markdown_content += f"{key}: {value}\n"
        markdown_content += f"---\n\n"
        markdown_content += f"# {market} Market Brief\n\n"
        markdown_content += synthesis_text.strip()
        
        # Write file (overwrite if exists)
        with open(market_file, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
            
        return True
        
    except Exception as e:
        # Log error but don't abort pipeline
        print(f"Obsidian sync failed for {market}: {str(e)}")
        return False


if __name__ == "__main__":
    # Test function
    test_market = "Yelahanka"
    test_synthesis = """This is a test synthesis for Yelahanka market.
    Current trends show increasing demand for residential properties.
    PSF range: ₹5500-₹7500.
    Recommendation: Proceed with caution due to market volatility."""
    
    result = sync_to_obsidian(test_market, test_synthesis)
    print(f"Obsidian sync test: {'SUCCESS' if result else 'FAILED'}")