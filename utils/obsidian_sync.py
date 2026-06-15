"""
RE_OS — Obsidian Sync
Writes market brief to the LLS wiki vault after every CEO synthesis.
Target: D:\Brain\JINU JOSHI\03 LLS\01 Wiki\markets\{market}.md
"""

from datetime import datetime
from pathlib import Path

from loguru import logger

from config.settings import OBSIDIAN_VAULT_PATH


def sync_to_obsidian(
    market: str,
    synthesis_text: str,
    confidence: float = 0.7,
    sources: int = 1,
    is_estimated: bool = False,
) -> bool:
    """Write market brief to Obsidian wiki vault.

    Args:
        market: Market name (e.g. 'Yelahanka').
        synthesis_text: CEO synthesis to write as body.
        confidence: Data confidence score 0-1 (pass is_estimated=True to cap at 0.5).
        sources: Number of data sources contributing to this brief.
        is_estimated: True when data is FALLBACK/ESTIMATED — caps confidence at 0.5.

    Returns:
        True on success, False on any filesystem error.
    """
    try:
        if is_estimated:
            confidence = min(confidence, 0.5)
        confidence = round(max(0.0, min(1.0, confidence)), 2)

        vault_path = Path(OBSIDIAN_VAULT_PATH)
        market_file = vault_path / "markets" / f"{market}.md"
        market_file.parent.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        frontmatter_lines = [
            "---",
            "type: wiki",
            f"date: {today}",
            "area: lls",
            f"market: {market}",
            f"confidence: {confidence}",
            f"sources: {sources}",
            f"last_confirmed: {today}",
            "ai_generated: true",
            "---",
            "",
        ]
        body = "\n".join(frontmatter_lines)
        body += f"# {market} Market Brief\n\n"
        if is_estimated:
            body += "> **Data quality: ESTIMATED** — live RERA scrape unavailable. Confidence capped at 0.5.\n\n"
        body += synthesis_text.strip()

        with open(market_file, "w", encoding="utf-8") as f:
            f.write(body)

        logger.info(
            f"[ObsidianSync] {market} → {market_file} (confidence={confidence})"
        )

        # Append one-liner to today's daily log (T-299)
        try:
            daily_log = vault_path.parent / "01 Daily" / f"[AI] {today}.md"
            daily_log.parent.mkdir(parents=True, exist_ok=True)
            with open(daily_log, "a", encoding="utf-8") as f:
                f.write(
                    f"\n- RE_OS: {market} market brief synced (confidence: {confidence}, sources: {sources})\n"
                )
        except Exception as log_exc:
            logger.warning(
                f"[ObsidianSync] daily log append failed for {market}: {log_exc}"
            )

        return True

    except Exception as exc:
        logger.warning(f"[ObsidianSync] sync failed for {market}: {exc}")
        return False
