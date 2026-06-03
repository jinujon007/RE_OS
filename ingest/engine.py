"""
RE_OS — Ingest Engine (Sprint 61 — Unified Ingest Engine)

Orchestrates the full ingest lifecycle:

    1. Plugin discovery & registration
    2. Parallel execution via ThreadPoolExecutor
    3. Token-bucket rate limiting (global + optional per-plugin buckets)
    4. SHA-256 deduplication against ingest_log (with in-memory bloom/ set cache)
    5. Exponential backoff on plugin run failures
    6. Structured IngestReport with per-plugin-run statistics
    7. Prometheus metrics for production observability
    8. Graceful cancellation on shutdown signal
"""

from __future__ import annotations

import json
import signal
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger

__all__ = [
    "IngestEngine", "IngestReport", "PluginRunStats",
    "TokenBucket", "create_engine",
]
from sqlalchemy import text

from utils.db import get_engine
from ingest.base import DataPlugin, ParsedRecord
from ingest.writer import IngestWriter


# ── Constants ──────────────────────────────────────────────────────────────────

_MARKET_CANONICAL: dict[str, str] = {
    "yelahanka": "Yelahanka",
    "devanahalli": "Devanahalli",
    "hebbal": "Hebbal",
    "all": "all",
}

_VALID_MARKETS = frozenset({"Yelahanka", "Devanahalli", "Hebbal"})

_DEDUP_CACHE_MAX = 50000  # max entries in local dedup LRU
_MAX_RECORDS_PER_PLUGIN = 10000  # safety cap per single plugin run


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class PluginRunStats:
    """Aggregated statistics for a single plugin × market execution."""
    plugin_id: str
    market: str
    status: str = "pending"
    records_scraped: int = 0
    records_written: int = 0
    records_deduped: int = 0
    records_failed: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""

    def __str__(self) -> str:
        return (
            f"[{self.plugin_id}/{self.market}] "
            f"{self.status}: {self.records_written}W + {self.records_deduped}D "
            f"+ {self.records_failed}F in {self.duration_seconds:.1f}s"
        )


@dataclass
class IngestReport:
    """Top-level report returned by :meth:`IngestEngine.run_all`."""
    run_id: str
    started_at: datetime
    completed_at: datetime | None = None
    total_duration_seconds: float = 0.0
    plugin_stats: list[PluginRunStats] = field(default_factory=list)
    global_records_written: int = 0
    global_records_deduped: int = 0
    global_records_failed: int = 0

    @property
    def all_succeeded(self) -> bool:
        return all(s.status == "success" for s in self.plugin_stats)

    @property
    def global_records_processed(self) -> int:
        return self.global_records_written + self.global_records_deduped + self.global_records_failed

    @property
    def succeeded_plugins(self) -> list[PluginRunStats]:
        return [s for s in self.plugin_stats if s.status == "success"]

    @property
    def failed_plugins(self) -> list[PluginRunStats]:
        return [s for s in self.plugin_stats if s.status == "failed"]

    def summary(self) -> str:
        """Compact one-line summary for logging."""
        return (
            f"run={self.run_id} duration={self.total_duration_seconds:.1f}s "
            f"written={self.global_records_written} deduped={self.global_records_deduped} "
            f"failed={self.global_records_failed} plugins={len(self.plugin_stats)}"
        )

    def __str__(self) -> str:
        return self.summary()


# ── Helpers ────────────────────────────────────────────────────────────────────


def _normalize_market(raw: str) -> str:
    """Normalise a market string to canonical form.

    Returns the input unchanged if it is already canonical; falls back to
    *raw* if no canonical mapping exists (logging a warning).
    """
    if raw in _VALID_MARKETS:
        return raw
    key = raw.strip().lower()
    canonical = _MARKET_CANONICAL.get(key)
    if canonical:
        return canonical
    logger.warning("[IngestEngine] unknown market '{}' — using as-is", raw)
    return raw


def _generate_run_id() -> str:
    """Short hex run identifier for log correlation."""
    return uuid.uuid4().hex[:12]


def _safe_json(data: dict) -> str:
    """JSON-serialise *data* with a fallback for non-serializable values."""
    try:
        return json.dumps(data, sort_keys=True, default=str)
    except (TypeError, ValueError):
        safe = {k: str(v) if isinstance(v, (dict, list)) else v for k, v in data.items()}
        return json.dumps(safe, sort_keys=True, default=str)


def _backoff_sleep(attempt: int, base: float = 2.0, max_delay: float = 60.0) -> None:
    """Exponential backoff sleep. ``attempt`` is 0-indexed."""
    delay = min(base * (2 ** attempt), max_delay)
    time.sleep(delay)


# ── Token Bucket (thread-safe) ─────────────────────────────────────────────────


class TokenBucket:
    """Thread-safe token-bucket rate limiter.

    Usage::

        bucket = TokenBucket(rate=5.0, capacity=10)
        bucket.acquire()   # blocks until a token is available
    """

    def __init__(self, rate: float, capacity: int) -> None:
        if rate <= 0:
            raise ValueError(f"rate must be > 0, got {rate}")
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> float:
        """Block until *tokens* are available, then consume them.

        Returns the wait time in seconds (always 0.0 for compatibility).
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens < tokens:
                sleep_time = (tokens - self._tokens) / self._rate
                time.sleep(sleep_time)
                self._tokens = 0.0
            else:
                self._tokens -= tokens
                sleep_time = 0.0
        return sleep_time

    @property
    def available(self) -> float:
        """Read-only snapshot of currently available tokens."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            return min(self._capacity, self._tokens + elapsed * self._rate)


# ── Dedup cache (local) ────────────────────────────────────────────────────────


class _DedupCache:
    """Simple bounded set for recently-seen hashes.

    Avoids hammering ingest_log for every record in a batch.
    Falls back to DB check on miss.
    """

    def __init__(self, maxsize: int = _DEDUP_CACHE_MAX) -> None:
        self._maxsize = maxsize
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def _seed_from_db(self) -> None:
        """Pre-populate with recent hashes from the DB (last 24 h)."""
        try:
            with get_engine().connect() as conn:
                rows = conn.execute(
                    text("SELECT raw_hash FROM ingest_log WHERE created_at > NOW() - INTERVAL '24 hours' AND raw_hash IS NOT NULL")
                ).fetchall()
            with self._lock:
                for (h,) in rows:
                    if h and len(self._seen) < self._maxsize:
                        self._seen.add(h)
            logger.debug("[DedupCache] seeded with {} hashes from ingest_log", len(rows))
        except Exception as exc:
            logger.debug("[DedupCache] DB seed skipped: {}", exc)

    def check_and_add(self, raw_hash: str) -> bool:
        """Return True if *raw_hash* is already known (duplicate); store it otherwise."""
        with self._lock:
            if raw_hash in self._seen:
                return True
            if len(self._seen) < self._maxsize:
                self._seen.add(raw_hash)
        return False

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


# ── Prometheus metrics (lazy) ──────────────────────────────────────────────────


def _metrics_counter(name: str, documentation: str, labelnames: tuple[str, ...]):
    from prometheus_client import Counter
    return Counter(name, documentation, labelnames)


# Lazy-loaded at first use to avoid import-order issues.
_INGEST_RUNS_TOTAL = None
_INGEST_RECORDS_TOTAL = None
_INGEST_DURATION_SECONDS = None


def _get_ingest_metrics():
    global _INGEST_RUNS_TOTAL, _INGEST_RECORDS_TOTAL, _INGEST_DURATION_SECONDS
    if _INGEST_RUNS_TOTAL is None:
        _INGEST_RUNS_TOTAL = _metrics_counter(
            "ingest_runs_total", "Ingest plugin runs", ("plugin", "market", "status"),
        )
        _INGEST_RECORDS_TOTAL = _metrics_counter(
            "ingest_records_total", "Ingest records processed",
            ("plugin", "market", "action"),  # action: written / deduped / failed
        )
        from prometheus_client import Histogram
        _INGEST_DURATION_SECONDS = Histogram(
            "ingest_duration_seconds", "Ingest plugin run duration",
            ("plugin", "market"), buckets=(1, 5, 10, 30, 60, 120, 300, 600),
        )
    return _INGEST_RUNS_TOTAL, _INGEST_RECORDS_TOTAL, _INGEST_DURATION_SECONDS


# ── Shutdown coordination ──────────────────────────────────────────────────────


class _ShutdownFlag:
    """Thread-safe flag checked by long-running operations."""

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def reset(self) -> None:
        with self._lock:
            self._cancelled = False


# ── Main Engine ────────────────────────────────────────────────────────────────


class IngestEngine:
    """Orchestrator for the plugin-based ingest pipeline.

    Typical usage::

        engine = IngestEngine(max_workers=4, global_rate=5.0)
        engine.register(MyReraPlugin())
        engine.register_all([MyIgrPlugin(), MyNewsPlugin()])
        report = engine.run_all(["Yelahanka", "Devanahalli"])
        print(report.global_records_written)
    """

    def __init__(
        self,
        max_workers: int = 4,
        global_rate: float = 5.0,
        dedup_cache_size: int = _DEDUP_CACHE_MAX,
        install_signal_handlers: bool = True,
    ) -> None:
        self._plugins: dict[str, DataPlugin] = {}
        self._max_workers = max_workers
        self._rate_limiter = TokenBucket(rate=global_rate, capacity=int(global_rate))
        self._dedup = _DedupCache(maxsize=dedup_cache_size)
        self._writer = IngestWriter()
        self._shutdown = _ShutdownFlag()
        self._run_lock = threading.Lock()
        self._lock = threading.Lock()
        self._is_running = False

        if install_signal_handlers:
            signal.signal(signal.SIGINT, lambda s, f: self.cancel())
            signal.signal(signal.SIGTERM, lambda s, f: self.cancel())

    # ── Plugin registry ────────────────────────────────────────────────────────

    def register(self, plugin: DataPlugin) -> None:
        pid = plugin.plugin_id
        with self._lock:
            if pid in self._plugins:
                logger.warning("[IngestEngine] plugin '{}' already registered — overwriting", pid)
            self._plugins[pid] = plugin
        logger.info("[IngestEngine] registered plugin: {} ({})", pid, plugin.source_id)

    def register_all(self, plugins: list[DataPlugin]) -> None:
        for p in plugins:
            self.register(p)

    @property
    def registered_plugins(self) -> list[str]:
        with self._lock:
            return list(self._plugins.keys())

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _is_duplicate(self, raw_hash: str) -> bool:
        """Local-cache-fast duplicate check with DB fallback."""
        if self._dedup.check_and_add(raw_hash):
            return True
        try:
            with get_engine().connect() as conn:
                row = conn.execute(
                    text("SELECT 1 FROM ingest_log WHERE raw_hash = :h LIMIT 1"),
                    {"h": raw_hash},
                ).fetchone()
                return row is not None
        except Exception:
            return False

    def _log_ingest(
        self,
        record: ParsedRecord,
        plugin_id: str,
        status: str,
        error_message: str = "",
        validation_errors: list[str] | None = None,
    ) -> None:
        """Write an audit row to ingest_log (best-effort, never raises)."""
        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO ingest_log
                            (plugin_id, source_id, market, entity_type, entity_id,
                             data, raw_hash, confidence, validation_errors,
                             status, error_message, scraped_at)
                        VALUES
                            (:pid, :sid, :mkt, :etype, :eid,
                             :data, :hash, :conf, :verrs,
                             :status, :err, :scraped)
                    """),
                    {
                        "pid": plugin_id,
                        "sid": record.source_id,
                        "mkt": record.market,
                        "etype": record.entity_type,
                        "eid": record.source_id,
                        "data": _safe_json(record.data),
                        "hash": record.raw_hash,
                        "conf": record.confidence,
                        "verrs": json.dumps(validation_errors or []),
                        "status": status,
                        "err": error_message,
                        "scraped": record.scraped_at,
                    },
                )
        except Exception as exc:
            logger.warning("[IngestEngine] ingest_log write failed: {}", exc)

    # ── Single plugin runner (runs in a thread-pool worker) ────────────────────

    def _run_plugin(
        self,
        plugin: DataPlugin,
        market: str,
        max_retries: int = 3,
    ) -> PluginRunStats:
        """Execute one plugin for one market.  Designed for ThreadPoolExecutor."""
        pid = plugin.plugin_id
        norm_market = _normalize_market(market)
        stats = PluginRunStats(plugin_id=pid, market=norm_market)
        start = time.monotonic()

        obs_start = time.monotonic()

        # ── Phase 1: Scrape (with retries) ──────────────────────────────────────
        records: list[ParsedRecord] = []
        for attempt in range(max_retries + 1):
            if self._shutdown.is_cancelled:
                stats.status = "cancelled"
                stats.error_message = "cancelled before scrape"
                stats.duration_seconds = time.monotonic() - start
                return stats

            try:
                raw_records = plugin.run(norm_market)
                if len(raw_records) > _MAX_RECORDS_PER_PLUGIN:
                    logger.warning(
                        "[IngestEngine] {}/{} returned {} records — capping at {}",
                        pid, norm_market, len(raw_records), _MAX_RECORDS_PER_PLUGIN,
                    )
                    raw_records = raw_records[:_MAX_RECORDS_PER_PLUGIN]
                records = raw_records
                stats.records_scraped = len(records)
                break
            except Exception as exc:
                stats.error_message = str(exc)
                if attempt < max_retries:
                    logger.warning(
                        "[IngestEngine] {}/{} attempt {}/{} failed: {} — retrying",
                        pid, norm_market, attempt + 1, max_retries, exc,
                    )
                    _backoff_sleep(attempt)
                else:
                    logger.error(
                        "[IngestEngine] {}/{} exhausted {} retries: {}",
                        pid, norm_market, max_retries, exc,
                    )
                    stats.status = "failed"
                    stats.duration_seconds = time.monotonic() - start
                    return stats

        # ── Phase 2: Process each record ────────────────────────────────────────
        written = 0
        deduped = 0
        failed = 0

        for record in records:
            if self._shutdown.is_cancelled:
                stats.status = "cancelled"
                break

            # Validate record market matches the requested market
            if record.market and _normalize_market(record.market) != norm_market:
                logger.warning(
                    "[IngestEngine] {}/{} record market mismatch: expected '{}', got '{}' — skipping",
                    pid, norm_market, norm_market, record.market,
                )
                failed += 1
                self._log_ingest(record, pid, "validation_error", error_message=f"market mismatch: expected {norm_market}, got {record.market}")
                continue

            self._rate_limiter.acquire()

            # Dedup check
            if self._is_duplicate(record.raw_hash):
                deduped += 1
                continue

            # Validation
            validation = plugin.validate(record)
            if not validation.valid:
                failed += 1
                self._log_ingest(
                    record, pid, "validation_error",
                    error_message="; ".join(validation.errors),
                    validation_errors=validation.errors,
                )
                continue

            # Write
            ok = self._writer.write(record)
            if ok:
                written += 1
                self._log_ingest(record, pid, "success")
            else:
                failed += 1
                self._log_ingest(record, pid, "write_error", error_message="writer returned False")

        stats.records_written = written
        stats.records_deduped = deduped
        stats.records_failed = failed
        if stats.status != "cancelled":
            stats.status = "success" if failed == 0 else "partial"
        stats.duration_seconds = time.monotonic() - start

        # ── Prometheus ──────────────────────────────────────────────────────────
        try:
            runs_counter, records_counter, duration_hist = _get_ingest_metrics()
            runs_counter.labels(plugin=pid, market=norm_market, status=stats.status).inc()
            records_counter.labels(plugin=pid, market=norm_market, action="written").inc(written)
            records_counter.labels(plugin=pid, market=norm_market, action="deduped").inc(deduped)
            records_counter.labels(plugin=pid, market=norm_market, action="failed").inc(failed)
            duration_hist.labels(plugin=pid, market=norm_market).observe(stats.duration_seconds)
        except Exception as exc:
            logger.debug("[IngestEngine] metrics update failed: {}", exc)

        return stats

    # ── Public API ──────────────────────────────────────────────────────────────

    def run_all(self, markets: list[str] | None = None) -> IngestReport:
        """Run every registered plugin for every *market* in parallel.

        Returns an :class:`IngestReport` with per-plugin-run statistics.
        Set *markets* to ``None`` to use the global ``TARGET_MARKETS`` setting.

        The engine can be cancelled via :meth:`cancel` — partially completed
        runs report ``cancelled`` status in their stats.
        """
        run_id = _generate_run_id()
        report = IngestReport(run_id=run_id, started_at=datetime.now(timezone.utc))
        logger.info("[IngestEngine] run {} started — {} plugins registered", run_id, len(self._plugins))

        if not self._plugins:
            logger.warning("[IngestEngine] no plugins registered — nothing to run")
            report.completed_at = datetime.now(timezone.utc)
            return report

        if not self._run_lock.acquire(blocking=False):
            logger.error("[IngestEngine] run {} — a previous run is still in progress; rejecting", run_id)
            report.completed_at = datetime.now(timezone.utc)
            report.total_duration_seconds = 0.0
            return report

        try:
            if markets is None:
                from config.settings import TARGET_MARKETS
                markets = TARGET_MARKETS

            # Seed dedup cache at run start
            self._dedup._seed_from_db()
            self._shutdown.reset()
            self._is_running = True

            tasks: list[tuple[DataPlugin, str]] = [
                (plugin, market)
                for plugin in self._plugins.values()
                for market in markets
            ]

            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                future_map = {
                    executor.submit(self._run_plugin, plugin, market): (plugin.plugin_id, market)
                    for plugin, market in tasks
                }

                for future in as_completed(future_map):
                    pid, market = future_map[future]
                    try:
                        stats = future.result()
                        report.plugin_stats.append(stats)
                        report.global_records_written += stats.records_written
                        report.global_records_deduped += stats.records_deduped
                        report.global_records_failed += stats.records_failed
                        logger.info(
                            "[IngestEngine] {}/{}: {} written + {} deduped + {} failed in {:.1f}s",
                            pid, market,
                            stats.records_written, stats.records_deduped,
                            stats.records_failed, stats.duration_seconds,
                        )
                    except Exception as exc:
                        logger.error("[IngestEngine] {}/{} unhandled exception: {}", pid, market, exc)

        except Exception as exc:
            logger.error("[IngestEngine] run {} fatal error: {}", run_id, exc)
            raise
        finally:
            self._is_running = False
            self._run_lock.release()

        report.completed_at = datetime.now(timezone.utc)
        report.total_duration_seconds = (report.completed_at - report.started_at).total_seconds()
        logger.info(
            "[IngestEngine] run {} complete — {} total, {} written in {:.1f}s",
            run_id, report.global_records_written + report.global_records_deduped,
            report.global_records_written, report.total_duration_seconds,
        )
        return report

    def cancel(self) -> None:
        """Signal all in-flight plugin runs to stop at the next safe point.

        Call from a signal handler or watchdog thread.

        Example::

            engine = IngestEngine()
            signal.signal(signal.SIGINT, lambda s, f: engine.cancel())
            report = engine.run_all()
        """
        logger.warning("[IngestEngine] cancellation requested — stopping after current records")
        self._shutdown.cancel()


# ── Convenience factory ────────────────────────────────────────────────────────


def create_engine(
    plugins: list[DataPlugin] | None = None,
    max_workers: int = 4,
    global_rate: float = 5.0,
) -> IngestEngine:
    """Create and return a pre-configured :class:`IngestEngine`.

    Args:
        plugins: If provided, registers them all before returning.
        max_workers: Thread-pool size.
        global_rate: Global token-bucket rate (tokens/second).
    """
    engine = IngestEngine(max_workers=max_workers, global_rate=global_rate)
    if plugins:
        engine.register_all(plugins)
    return engine
