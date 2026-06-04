"""
RE_OS — Intel Registry (Sprint 62 — GATE-46)
==============================================

IntelRegistry orchestrates all 5 intelligence modules, returning a composite
IntelPackage. Features:

  * 1-hour memoization per cache key (survey_no + market + financial params)
  * Partial-failure graceful: one module failing never blocks other 4
  * Force-refresh via ``force_refresh=True`` bypasses cache
  * Bounded LRU cache (1024 entries) with ``collections.OrderedDict``
  * Shorter TTL (5 min) for partial-success results vs full-success (60 min)
  * Market-filtered cache invalidation via parsed key tokens

Risk Register:
| Risk | Impact | Mitigation |
|------|--------|------------|
| 1-hour stale financial data | Wrong deal recommendation | ``force_refresh`` param; invalidate_cache() per market |
| OOM from unbounded cache | Process killed | OrderedDict capped at 1024; partial TTL=5min limits stale entries |
| Thread-race on cache write | Lost update or stale read | RLock on all cache ops; near-atomic set vs expiry check |
| Database transient failure | 4/5 modules return OK, 1 cached as error | Partial cache stored with 5min TTL, next call retries |

Usage::

    from intelligence.registry import IntelRegistry
    pkg = IntelRegistry().get_full_picture(
        "45/2", "Devanahalli", 5200, 4000, "compare",
    )
    print(pkg.market_pulse, pkg.demand_signals)
    print(pkg.all_modules_success, pkg.errors)
"""
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

__all__ = ["IntelRegistry", "IntelPackage"]

_POSITIVE_TTL: float = 3600.0
_PARTIAL_TTL: float = 300.0
_MAX_CACHE_SIZE: int = 1024

_DEFAULT_GUIDANCE_PSF: float = 4000.0
_DEFAULT_SELL_PSF: float = 5000.0
_DEFAULT_CONSTRUCTION_COST_PSF: float = 2200.0


@dataclass
class IntelPackage:
    """Composite output of all 5 intelligence modules.

    Attributes:
        survey_no:       Sanitised survey number (e.g. "45/2").
        market:          Canonical market name from DB.
        collected_at:    ISO-8601 timestamp of collection.
        elapsed_ms:      Wall-clock time for ``get_full_picture``.
        market_pulse:     ``MarketPulse`` or ``None`` on failure.
        legal_picture:   ``LegalPicture`` or ``None`` on failure.
        financial_evaluation: ``FinancialEvaluation`` or ``None`` on failure.
        land_picture:    ``LandPicture`` or ``None`` on failure.
        demand_signals:  ``DemandSignals`` or ``None`` on failure.
        module_status:   ``{module_name: "OK"|"ERROR"}`` per module.
        errors:          Human-readable error strings for failed modules.
        all_modules_success: ``True`` iff every module returned ``"OK"``.
        deal_type:       Deal structure hint (included for downstream routing).
    """
    survey_no: str
    market: str
    collected_at: str
    elapsed_ms: float = 0.0

    market_pulse: Any = None
    legal_picture: Any = None
    financial_evaluation: Any = None
    land_picture: Any = None
    demand_signals: Any = None

    module_status: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    all_modules_success: bool = False

    deal_type: str = "compare"

    def __str__(self) -> str:
        ok = sum(1 for v in self.module_status.values() if v == "OK")
        total = len(self.module_status)
        return (
            f"[IntelPackage:{self.market}/{self.survey_no}] "
            f"{ok}/{total} modules OK | {self.elapsed_ms:.0f}ms | "
            f"errors={len(self.errors)}"
        )

    def __repr__(self) -> str:
        return (
            f"IntelPackage(survey_no={self.survey_no!r}, market={self.market!r}, "
            f"status={self.module_status}, elapsed_ms={self.elapsed_ms:.1f})"
        )


class _LRUCache:
    """Thread-safe bounded TTL cache backed by ``OrderedDict``.

    Evicts the least-recently-used entry when ``max_size`` is exceeded.
    """

    def __init__(self, max_size: int = _MAX_CACHE_SIZE):
        self._lock = threading.RLock()
        self._store: OrderedDict[str, tuple[float, IntelPackage]] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> IntelPackage | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expiry, pkg = entry
            if time.time() >= expiry:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return pkg

    def set(self, key: str, pkg: IntelPackage):
        ttl = _POSITIVE_TTL if pkg.all_modules_success else _PARTIAL_TTL
        with self._lock:
            self._store[key] = (time.time() + ttl, pkg)
            self._store.move_to_end(key)
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def _parse_key(self, key: str) -> dict[str, str]:
        parts = key.split("|", 4)
        return {
            "survey_no": parts[0] if len(parts) > 0 else "",
            "market": parts[1] if len(parts) > 1 else "",
        }

    def invalidate(self, survey_no: str | None = None, market: str | None = None):
        with self._lock:
            if survey_no is None and market is None:
                self._store.clear()
                return
            keys_to_del = []
            for k in self._store:
                parsed = self._parse_key(k)
                if survey_no is not None and parsed["survey_no"] != survey_no:
                    continue
                if market is not None and parsed["market"].lower() != market.lower():
                    continue
                keys_to_del.append(k)
            for k in keys_to_del:
                del self._store[k]

    def clear(self):
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._store)


class IntelRegistry:
    """Compose results from all 5 intelligence modules into a single package.

    Usage::

        reg = IntelRegistry()
        pkg = reg.get_full_picture("45/2", "Devanahalli", 5200, 6000)
        if not pkg.all_modules_success:
            print("Degraded:", pkg.errors)
    """

    def __init__(self):
        self._cache = _LRUCache()

    def _cache_key(
        self,
        survey_no: str,
        market: str,
        land_area_sqft: float,
        sell_psf: float,
    ) -> str:
        return f"{survey_no}|{market}|{land_area_sqft}|{sell_psf}"

    def invalidate_cache(
        self, survey_no: str | None = None, market: str | None = None,
    ):
        self._cache.invalidate(survey_no, market)

    def get_full_picture(
        self,
        survey_no: str,
        market: str,
        land_area_sqft: float = 43560.0,
        sell_psf: float | None = None,
        deal_type: str = "compare",
        guidance_value_psf: float | None = None,
        construction_cost_psf: float = _DEFAULT_CONSTRUCTION_COST_PSF,
        force_refresh: bool = False,
    ) -> IntelPackage:
        """Run all 5 intelligence modules and return the composite package.

        Args:
            survey_no:           Survey number (e.g. ``"45/2"``).
            market:              Market name.
            land_area_sqft:      Land area in square feet.
            sell_psf:            Expected selling price per sqft. If ``None``
                                 or 0, falls back to ``market_pulse.avg_listing_psf``,
                                 then 5000.
            deal_type:           Deal structure hint (``"purchase"``, ``"jd"``,
                                 ``"jv"``, ``"compare"``). Stored in package
                                 for downstream routing; not passed to modules.
            guidance_value_psf:  Guidance value (KV) per sqft.
            construction_cost_psf: Construction cost per sqft.
            force_refresh:       If ``True`` bypasses 1-hour cache.

        Returns:
            IntelPackage — always returns, never raises.
        """
        from intelligence._shared import sanitize_market, sanitize_survey, validate_market

        s = sanitize_survey(survey_no)
        m = sanitize_market(market)
        if not s or not m:
            return IntelPackage(
                survey_no=s or survey_no,
                market=m or market,
                collected_at=datetime.now(timezone.utc).isoformat(),
                module_status={"registry": "ERROR"},
                errors=[f"Invalid input: survey=[{survey_no}] market=[{market}]"],
                deal_type=deal_type,
            )

        land = max(float(land_area_sqft), 0.0)
        psf = max(float(sell_psf or 0), 0.0)

        key = self._cache_key(s, m, land, psf)
        if not force_refresh:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        mi = validate_market(m)
        pkg = IntelPackage(
            survey_no=s,
            market=mi["name"] if mi else m,
            collected_at=datetime.now(timezone.utc).isoformat(),
            module_status={},
            deal_type=deal_type,
        )

        start = time.perf_counter()
        gv = guidance_value_psf or _DEFAULT_GUIDANCE_PSF

        self._run_module(pkg, "market_pulse", self._get_market_pulse, m)
        self._run_module(pkg, "demand_signals", self._get_demand_signals, m)
        self._run_module(pkg, "land_picture", self._get_land_picture, s, m)
        self._run_module(pkg, "legal_picture", self._get_legal_picture, s, m)

        actual_psf = psf
        if actual_psf <= 0:
            if (
                pkg.market_pulse
                and hasattr(pkg.market_pulse, "avg_listing_psf")
                and pkg.market_pulse.avg_listing_psf
            ):
                actual_psf = pkg.market_pulse.avg_listing_psf
            else:
                actual_psf = _get_market_psf_fallback(m_raw)
        self._run_module(
            pkg, "financial_evaluation", self._get_financial_evaluation,
            m, land, actual_psf, gv, construction_cost_psf,
        )

        pkg.all_modules_success = all(
            v == "OK" for v in pkg.module_status.values()
        )
        pkg.elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

        self._cache.set(key, pkg)
        return pkg

    def _run_module(
        self,
        pkg: IntelPackage,
        attr: str,
        fn: Any,
        *args: Any,
    ) -> None:
        try:
            result = fn(*args)
            setattr(pkg, attr, result)
            pkg.module_status[attr] = "OK"
        except Exception as exc:
            logger.warning("[IntelRegistry] {} failed: {}", attr, exc)
            pkg.module_status[attr] = "ERROR"
            pkg.errors.append(f"{attr}: {exc}")

    @staticmethod
    def _get_market_pulse(market: str):
        from intelligence.market_intel import MarketIntel
        return MarketIntel(caller="IntelRegistry").get_pulse(market)

    @staticmethod
    def _get_demand_signals(market: str):
        from intelligence.demand_intel import DemandIntel
        return DemandIntel(caller="IntelRegistry").get_signals(market)

    @staticmethod
    def _get_land_picture(survey_no: str, market: str):
        from intelligence.land_intel import LandIntel
        return LandIntel(caller="IntelRegistry").get_land_picture(survey_no, market)

    @staticmethod
    def _get_legal_picture(survey_no: str, market: str):
        from intelligence.legal_intel import LegalIntel
        return LegalIntel(caller="IntelRegistry").get_survey_picture(survey_no, market)

    @staticmethod
    def _get_financial_evaluation(
        market: str,
        land_area_sqft: float,
        sell_psf: float,
        guidance_value_psf: float,
        construction_cost_psf: float,
    ):
        from intelligence.financial_intel import FinancialIntel, _get_market_psf_fallback
        return FinancialIntel(caller="IntelRegistry").evaluate(
            market=market,
            land_area_sqft=land_area_sqft,
            sell_psf=sell_psf,
            guidance_value_psf=guidance_value_psf,
            construction_cost_psf=construction_cost_psf,
        )


if __name__ == "__main__":
    reg = IntelRegistry()
    pkg = reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
    print(repr(pkg))
    print(f"  market_pulse={bool(pkg.market_pulse)}")
    print(f"  demand_signals={bool(pkg.demand_signals)}")
    print(f"  land_picture={bool(pkg.land_picture)}")
    print(f"  legal_picture={bool(pkg.legal_picture)}")
    print(f"  financial_evaluation={bool(pkg.financial_evaluation)}")
    print(f"  status={pkg.module_status}")
    print(f"  errors={pkg.errors}")
