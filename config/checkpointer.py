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

Thread/Process Safety:
    save() uses an atomic write — serialise to a per-PID temp file then os.replace().
    os.replace() is atomic on POSIX (same filesystem, rename(2) syscall), so a concurrent
    reader never sees a partial file. This covers the main production race: the scheduler
    and a dashboard-triggered subprocess writing to the same checkpoint on the same day.

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
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs"
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
        return os.path.join(self.base_dir, slug, "checkpoints", f"{task}_{today}.json")

    # ── Public API ─────────────────────────────────────────────────────────────

    def save(self, market: str, task: str, data) -> str:
        """Persist data to disk atomically. Returns the file path written.

        Uses write-to-temp-then-rename so concurrent processes (scheduler vs.
        dashboard-triggered run) never see a partial file mid-write.
        """
        path = self._path(market, task)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # Write to a PID-unique temp file in the same directory, then rename atomically.
        tmp = path + f".{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

        logger.info(f"[Checkpoint] Saved  {market}/{task} → {os.path.basename(path)}")
        return path

    def load(self, market: str, task: str):
        """Load today's checkpoint. Returns None if not found or unreadable."""
        path = self._path(market, task)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                f"[Checkpoint] Unreadable checkpoint at {path}: {exc} — treating as missing"
            )
            return None
        size = len(data) if isinstance(data, list) else "dict"
        logger.info(
            f"[Checkpoint] Loaded {market}/{task} ← {os.path.basename(path)} ({size} records)"
        )
        return data

    def exists(self, market: str, task: str) -> bool:
        return os.path.exists(self._path(market, task))

    def path(self, market: str, task: str) -> str:
        return self._path(market, task)

    def cleanup_old(self, market: str, keep_days: int = 7) -> int:
        """Delete checkpoint files older than keep_days. Returns count removed.

        Prevents unbounded checkpoint accumulation on long-running deployments.
        Called automatically by run_all_markets() after a successful sweep.
        """
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).date()
        slug = self._market_slug(market)
        cp_dir = os.path.join(self.base_dir, slug, "checkpoints")
        removed = 0

        if not os.path.isdir(cp_dir):
            return 0

        for fname in os.listdir(cp_dir):
            if not fname.endswith(".json"):
                continue
            # Filename: {task}_{YYYY-MM-DD}.json — date is the last segment before .json
            parts = fname[:-5].rsplit("_", 1)
            if len(parts) != 2:
                continue
            try:
                file_date = date.fromisoformat(parts[1])
            except ValueError:
                continue
            if file_date < cutoff:
                try:
                    os.unlink(os.path.join(cp_dir, fname))
                    removed += 1
                except OSError:
                    pass

        if removed:
            logger.info(f"[Checkpoint] Pruned {removed} old files for {market} (>{keep_days}d)")
        return removed
