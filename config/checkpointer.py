"""
RE_OS — Task Checkpointer
──────────────────────────
Saves intermediate pipeline outputs to disk after each stage.

Why: If the crew fails at Stage 4 (analyst), you should not have to re-scrape RERA.
     The scraper saves its output; the organizer reads it. Failed runs resume cheaply.

Convention:
    outputs/{market_slug}/checkpoints/{task}_{YYYY-MM-DD}.json

One checkpoint per task per market per day.
If a checkpoint for today exists, that stage can be skipped.

Usage:
    cp = Checkpointer()
    cp.save("Yelahanka", "rera_scraped", projects_list)
    projects = cp.load("Yelahanka", "rera_scraped")   # None if not found
    if cp.exists("Yelahanka", "rera_scraped"):
        ...
"""

import json
import os
from datetime import date
from loguru import logger


_BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "outputs"
)


class Checkpointer:
    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or _BASE_DIR

    # ── Path helpers ───────────────────────────────────────────────────────────

    def _market_slug(self, market: str) -> str:
        return market.lower().replace(" ", "_")

    def _path(self, market: str, task: str) -> str:
        today = date.today().isoformat()
        slug = self._market_slug(market)
        return os.path.join(
            self.base_dir, slug, "checkpoints", f"{task}_{today}.json"
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def save(self, market: str, task: str, data) -> str:
        """Persist data to disk. Returns the file path written."""
        path = self._path(market, task)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"[Checkpoint] Saved  {market}/{task} → {os.path.basename(path)}")
        return path

    def load(self, market: str, task: str):
        """Load today's checkpoint. Returns None if it doesn't exist."""
        path = self._path(market, task)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        size = len(data) if isinstance(data, list) else "dict"
        logger.info(
            f"[Checkpoint] Loaded {market}/{task} ← {os.path.basename(path)} ({size} records)"
        )
        return data

    def exists(self, market: str, task: str) -> bool:
        return os.path.exists(self._path(market, task))

    def path(self, market: str, task: str) -> str:
        return self._path(market, task)
