"""
J-14 Competitor Teardown — Land/Agri Parcel Coverage
Platforms: Zapkey, CRE Matrix, Propstack
Focus: North Bengaluru (Yelahanka, Devanahalli, Hebbal)
Question: Do these platforms have land-stage intel, and how deep?
"""

import asyncio
import os
import re
import json
from datetime import datetime
from pathlib import Path
from browser_use.llm.openai.chat import ChatOpenAI as BUChatOpenAI

# --- Config ---
with open("d:/Brain/JINU JOSHI/03 LLS/02 Projects/RE_market/RE_OS/.env") as _f:
    _env = _f.read()
SAMBANOVA_API_KEY = re.search(r"SAMBANOVA_API_KEY=(\S+)", _env).group(1)
OUTPUT_DIR = Path(
    "d:/Brain/JINU JOSHI/03 LLS/02 Projects/RE_market/RE_OS/outputs/j14_teardown"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PLATFORMS = {
    "zapkey": {
        "url": "https://zapkey.com",
        "task": (
            "Go to zapkey.com. I need to understand their land and agricultural plot coverage "
            "for North Bengaluru (Yelahanka, Devanahalli, Hebbal areas). "
            "Do the following steps:\n"
            "1. Search or navigate to find land/plot/agricultural property listings in Bengaluru. "
            "Look for filter options like 'Plot', 'Land', 'Agricultural Land', 'NA Plot'.\n"
            "2. Apply any available filters for Yelahanka or Devanahalli locality.\n"
            "3. Note: how many listings appear? What data fields are shown per listing "
            "(price, survey number, area in sqft/acres, seller name, registration date, "
            "guidance value, EC/encumbrance details)?\n"
            "4. Click on 1-2 individual listings and note what detail data is available "
            "(transaction history, ownership chain, legal documents, RERA link if any).\n"
            "5. Check if they have any 'land records', 'deed search', 'survey number search', "
            "or 'registration data' section anywhere on the site.\n"
            "6. Note any login/paywall restrictions — what's free vs paid?\n"
            "Compile a detailed summary of findings."
        ),
    },
    "crematrix": {
        "url": "https://www.crematrix.com",
        "task": (
            "Go to crematrix.com (CRE Matrix — a commercial real estate data platform for India). "
            "I need to understand their land and agricultural plot/parcel coverage "
            "for North Bengaluru (Yelahanka, Devanahalli, Hebbal). "
            "Do the following steps:\n"
            "1. Navigate their site to find any land transaction data, plot listings, "
            "or agricultural land records for Bengaluru.\n"
            "2. Look for features like: deed/transaction search, land parcel data, "
            "survey number lookup, guidance value data, registration data.\n"
            "3. Check their product/feature pages — what asset types do they cover? "
            "Is land/plot/agricultural land explicitly listed?\n"
            "4. What geographic granularity do they offer for Bengaluru? Village-level? "
            "Survey number level? Taluk level?\n"
            "5. Note any login/paywall restrictions — what's visible without an account?\n"
            "6. Check pricing page if available — what tier includes land data?\n"
            "Compile a detailed summary of findings."
        ),
    },
    "propstack": {
        "url": "https://propstack.in",
        "task": (
            "Go to propstack.in (Propstack — Indian real estate data and CRM platform). "
            "I need to understand their land and agricultural plot/parcel data coverage "
            "for North Bengaluru (Yelahanka, Devanahalli, Hebbal). "
            "Do the following steps:\n"
            "1. Navigate to find any land/plot/agricultural property data or listings.\n"
            "2. Look for: transaction history search, land record lookup, survey number data, "
            "deed registration data, guidance value data.\n"
            "3. Check what property types they cover — is land/plot explicitly included?\n"
            "4. What geographic depth for Bengaluru? Village level? Survey number level?\n"
            "5. Do they have any 'market intelligence' or 'data analytics' product "
            "that covers land transactions?\n"
            "6. Note login/paywall restrictions — what's visible free vs paid?\n"
            "Compile a detailed summary of findings."
        ),
    },
}


async def run_teardown_for_platform(name: str, config: dict, llm) -> dict:
    """Run browser-use agent against one platform and return findings."""
    from browser_use import Agent

    print(f"\n{'=' * 60}")
    print(f"PLATFORM: {name.upper()}")
    print(f"URL: {config['url']}")
    print(f"{'=' * 60}\n")

    agent = Agent(
        task=config["task"],
        llm=llm,
        use_vision=True,
        max_failures=3,
        directly_open_url=config["url"],
        max_actions_per_step=8,
        use_judge=False,
    )

    try:
        history = await agent.run(max_steps=25)
        result = history.final_result() or "No final result captured."
        print(f"\n[{name}] DONE. Result length: {len(result)} chars")

        # Save raw result
        out_file = OUTPUT_DIR / f"{name}_raw.txt"
        out_file.write_text(result, encoding="utf-8")
        print(f"[{name}] Saved to {out_file}")

        return {"platform": name, "status": "success", "findings": result}

    except Exception as e:
        error_msg = str(e)
        print(f"\n[{name}] ERROR: {error_msg}")
        return {"platform": name, "status": "error", "findings": error_msg}


async def main():
    llm = BUChatOpenAI(
        model="Meta-Llama-3.3-70B-Instruct",
        api_key=SAMBANOVA_API_KEY,
        base_url="https://api.sambanova.ai/v1",
        temperature=0.1,
    )

    all_results = {}

    # Run platforms sequentially (one browser at a time — cleaner on 16GB RAM)
    for name, config in PLATFORMS.items():
        result = await run_teardown_for_platform(name, config, llm)
        all_results[name] = result

        # Save intermediate state after each platform
        interim_file = OUTPUT_DIR / "interim_results.json"
        interim_file.write_text(
            json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Save final combined JSON
    final_file = (
        OUTPUT_DIR / f"j14_teardown_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    )
    final_file.write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n\nAll results saved to: {final_file}")

    # Print summary
    print("\n" + "=" * 60)
    print("TEARDOWN COMPLETE — SUMMARY")
    print("=" * 60)
    for name, result in all_results.items():
        print(f"\n{name.upper()} — {result['status'].upper()}")
        if result["status"] == "success":
            # Print first 500 chars of findings
            print(
                result["findings"][:800]
                + ("..." if len(result["findings"]) > 800 else "")
            )


if __name__ == "__main__":
    asyncio.run(main())
