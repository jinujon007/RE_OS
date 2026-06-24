"""
RE_OS — Scraper Circuit Breaker (T-1327, GATE-128)

3-attempt exponential backoff (30s/60s/120s) + 7-day checkpoint cache fallback.

Failure cascade:
  1. fn() called with exponential backoff between retries (jitter ±25%)
  2. All attempts exhausted → glob-scan checkpoint dir for any <7d file
  3. Cache hit → return cached data + fire RERA_SCRAPER_FALLBACK Discord alert
  4. No cache or stale → raise CircuitOpenError (market, attempts, last_error)
"""

from __future__ import annotations

import glob as glob_mod
import json
import os
import random
import time
from typing import Any, Callable

from loguru import logger
from config.checkpointer import Checkpointer


_CACHE_TASK = "rera_scraped"
_MAX_BACKOFF = 300.0


class CircuitOpenError(Exception):
    """All attempts exhausted and no valid cache available.

    Structured fields for monitoring/automated triage:
      market: str         — market name that failed
      attempts_made: int  — number of live scrape attempts
      last_error: str     — last exception message from fn()
    """

    def __init__(
        self,
        message: str,
        market: str = "",
        attempts_made: int = 0,
        last_error: str = "",
    ):
        super().__init__(message)
        self.market = market
        self.attempts_made = attempts_made
        self.last_error = last_error


class ScraperResult:
    data: Any
    from_cache: bool
    cache_age_days: float | None
    attempts_made: int

    def __init__(
        self,
        data: Any,
        from_cache: bool = False,
        cache_age_days: float | None = None,
        attempts_made: int = 0,
    ):
        self.data = data
        self.from_cache = from_cache
        self.cache_age_days = cache_age_days
        self.attempts_made = attempts_made


class ScraperCircuitBreaker:
    """Retry with exponential backoff, then cache fallback.

    Usage:
        cb = ScraperCircuitBreaker("Yelahanka", max_attempts=3, base_delay=30.0)
        try:
            result = cb.run(my_scrape_fn, market="Yelahanka")
            print(result.data)
        except CircuitOpenError:
            # All attempts + cache exhausted
    """

    def __init__(
        self,
        market: str,
        max_attempts: int = 3,
        base_delay: float = 30.0,
    ):
        self.market = market
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self._checkpointer = Checkpointer()
        self._discord_alert_fired = False

    def run(self, fn: Callable, *args: Any, **kwargs: Any) -> ScraperResult:
        """Execute fn with retry + cache fallback.

        Returns ScraperResult on success or cache hit.
        Raises CircuitOpenError when all attempts fail and no valid cache.
        """
        last_error: Exception | None = None
        attempt = 0

        while attempt < self.max_attempts:
            try:
                data = fn(*args, **kwargs)
                return ScraperResult(
                    data=data,
                    from_cache=False,
                    cache_age_days=None,
                    attempts_made=attempt + 1,
                )
            except Exception as exc:
                last_error = exc
                attempt += 1
                logger.warning(
                    "[CircuitBreaker:{}] Attempt {}/{} failed: {}",
                    self.market, attempt, self.max_attempts, exc,
                )
                if attempt < self.max_attempts:
                    delay = min(
                        self.base_delay * (2 ** (attempt - 1)) * random.uniform(0.75, 1.25),
                        _MAX_BACKOFF,
                    )
                    logger.info(
                        "[CircuitBreaker:{}] Backoff {:.0f}s before retry {}",
                        self.market, delay, attempt + 1,
                    )
                    time.sleep(delay)

        cache = self._load_cache()
        if cache is not None:
            data, age_days = cache
            self._fire_cache_alert(age_days)
            return ScraperResult(
                data=data,
                from_cache=True,
                cache_age_days=age_days,
                attempts_made=self.max_attempts,
            )

        raise CircuitOpenError(
            f"[CircuitBreaker:{self.market}] "
            f"{self.max_attempts} attempts failed and no valid cache. "
            f"Last error: {last_error}",
            market=self.market,
            attempts_made=self.max_attempts,
            last_error=str(last_error) if last_error else "",
        )

    def _load_cache(self) -> tuple[Any, float] | None:
        """Find the most recent checkpoint file; return (data, age_days) or None.

        Scans checkpoint directory for files matching ``*<task>_*.json``,
        picks the one with the latest mtime. This covers the case where
        a prior day's checkpoint is still fresh (<7d) but today's hasn't
        been written yet.
        """
        cp = self._checkpointer
        slug = self.market.lower().replace(" ", "_")
        cp_dir = os.path.join(cp.base_dir, slug, "checkpoints")
        if not os.path.isdir(cp_dir):
            return None
        pattern = os.path.join(cp_dir, f"*{_CACHE_TASK}_*.json")
        candidates = sorted(glob_mod.glob(pattern), key=os.path.getmtime, reverse=True)
        if not candidates:
            return None
        latest = candidates[0]
        try:
            mtime = os.path.getmtime(latest)
        except OSError:
            return None
        age = (time.time() - mtime) / 86400.0
        if not self._is_cache_fresh(age):
            return None
        try:
            with open(latest, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return data, age

    @staticmethod
    def _is_cache_fresh(age_days: float, max_age: float = 7.0) -> bool:
        return age_days <= max_age

    def _fire_cache_alert(self, age_days: float) -> None:
        """Fire Discord alert once per breaker instance."""
        if self._discord_alert_fired:
            return
        self._discord_alert_fired = True
        title = "RERA_SCRAPER_FALLBACK"
        message = (
            f"[CircuitBreaker:{self.market}] All "
            f"{self.max_attempts} live attempts failed. "
            f"Falling back to cache ({age_days:.1f} days old)."
        )
        try:
            from utils.discord_notifier import send_ops_alert
            send_ops_alert(title, message)
        except Exception as exc:
            logger.warning(
                "[CircuitBreaker:{}] Discord alert send failed for {}: {}",
                self.market, title, exc,
            )
