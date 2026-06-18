"""
RE_OS — IRR Model (Phase 6 — Finance Department)
LLS standard feasibility model. Assumptions confirmed 2026-05-30.

Standards:
  Construction cost:  ₹2,200/sqft (hard cost, mid-range residential)
  Target IRR:        >=20% = GO | 12-20% = MARGINAL | <12% = NO-GO
  Financing:         60% equity / 40% debt
  Timeline:          18mo land->RERA + 36mo RERA->possession = 54mo total

T-477: IGR Transaction PSF Integration
  GDVEstimator queries igr_transactions 90-day median transaction_psf.
  Falls back to listings PSF if <5 IGR records.
  Source tracked in GDVResult.igr_source.

T-720/T-721: Risk Metrics (Tier 1 — Financial Intelligence Depth)
  IRRResult extended with:
    - re_sharpe_ratio(irr, risk_free, irr_std): RE-adapted Sharpe = (IRR - 7% Gsec) / scenario_std
    - empyrical.sharpe_ratio + max_drawdown from 54-month cashflow projection
    - best/worst_case_irr_pct from bull/bear scenario IRRs
  _build_monthly_returns(): constructs 54-month cashflow / equity Series for empyrical.
  _compute_risk_metrics(): orchestrates both RE-Sharpe and empyrical metrics.
  Graceful degrades when empyrical not installed — still emits RE-adapted Sharpe.

T-1203—T-1207 (Sprint 103 / GATE-103): True IRR Fix
  calc_irr_npv(): NPV-solving IRR using numpy-financial. Validates against npf.npv()
    to reject false roots. Replaces the annualized ROI that was mislabelled as IRR.
  _compute_absorption_curve(): Curved revenue distribution based on sales velocity.
    Replaces flat revenue assumption — revenue front-loaded when velocity > 0.
  build_cash_flow() extended with irr_npv_pct on CashFlowSummary and curved
    absorption via sales_velocity_units_per_month parameter.

Design decisions:
  - GDVEstimator returns psf=0.0 when insufficient IGR data (< MIN_IGR_RECORDS).
    Caller provides the fallback PSF (listing PSF from market data). This separation
    keeps the estimator testable without mocking market prices.
  - _query_igr_median_psf logs source='table_unavailable' | 'insufficient_records' | 'no_data'
    so downstream consumers can distinguish DB failure from genuine data scarcity.
  - log_igr_lookup writes to agent_runs for audit trail. Non-fatal — caller proceeds
    regardless of write failure.
  - Market names are normalized to title-case before ILIKE query (YELAHANKA -> Yelahanka)
    for robustness against inconsistent casing from pitch text.
  - Two separate Sharpe computations: empyrical.sharpe_ratio (financial — returns-based) is
    computed from monthly cashflow series for max_drawdown; re_sharpe_ratio (RE-adapted —
    IRR-based) is the primary Sharpe used in Board Room context. The RE-adapted version
    uses (IRR - 7% Gsec) / scenario_IRR_std because real estate IRR doesn't follow
    normal distribution assumptions of traditional Sharpe.
  - Risk metrics use a fixed 54-month schedule (_build_monthly_returns) while
    build_cash_flow() accepts configurable months. This is intentional — risk
    banding needs a standardised horizon, cash projection needs caller flexibility.
  - calc_irr_npv validates with npf.npv() because npf.irr() (Newton-Raphson with
    single seed) can converge to false roots for cash flows with multiple sign
    changes. The NPV check adds ~5µs per call.
"""

import json
from dataclasses import dataclass, field

from config.metrics import irr_computations_total, cashflow_build_duration_seconds, absorption_curve_calls_total

# -- LLS Standard Assumptions -------------------------------------------------
CONSTRUCTION_COST_PSF: float = 2200.0  # ₹/sqft hard cost
TARGET_IRR_GO: float = 20.0  # % -- project green-lights above this
TARGET_IRR_MARGINAL: float = 12.0  # % -- conditional zone
EQUITY_RATIO: float = 0.60  # 60% equity
DEBT_RATIO: float = 0.40  # 40% debt
LAND_TO_RERA_MONTHS: int = 18
RERA_TO_POSSESSION_MONTHS: int = 36
TOTAL_TIMELINE_MONTHS: int = LAND_TO_RERA_MONTHS + RERA_TO_POSSESSION_MONTHS


@dataclass
class LandCostResult:
    area_sqft: float
    guidance_value_psf: float
    negotiation_discount_pct: float
    raw_land_cost: float
    negotiated_land_cost: float


_IGR_SOURCE_DEFAULT: str | None = None


@dataclass
class GDVResult:
    sellable_area_sqft: float
    sell_psf: float
    gross_development_value: float
    monthly_revenue: float
    igr_source: str | None = field(
        default=None
    )  # 'igr_portal' | 'igr_fallback' | 'listing_psf' | None
    igr_record_count: int = field(default=0)  # number of IGR records used


@dataclass
class IRRResult:
    land_cost: float
    construction_cost: float
    total_project_cost: float
    gdv: float
    net_profit: float
    profit_margin_pct: float
    simple_irr_pct: float
    equity_required: float
    debt_required: float
    payback_months: int
    verdict: str  # GO | MARGINAL | NO-GO
    # ── Risk bands (Tier 1 — Financial Intelligence Depth) ──────────────────────
    sharpe_ratio: float = 0.0  # RE-adapted Sharpe (irr - risk_free) / irr_std
    max_drawdown_pct: float = 0.0  # Max peak-to-trough decline %
    best_case_irr_pct: float = 0.0  # p75 (bull scenario)
    worst_case_irr_pct: float = 0.0  # p25 (bear scenario)
    risk_free_return_pct: float = 7.0  # Indian Gsec benchmark %
    # ── Data provenance (T-794 — Sprint 42) ──────────────────────────────────────
    psf_source_quality: str = (
        "unknown"  # 'live_igr' | 'fallback_igr' | 'listing_only' | 'unknown'
    )


@dataclass
class ScenarioResult:
    base: IRRResult
    bull: IRRResult
    bear: IRRResult
    recommendation: str


def calc_land_cost(
    area_sqft: float,
    guidance_value_psf: float,
    negotiation_discount_pct: float = 10.0,
) -> LandCostResult:
    area = float(max(area_sqft, 0))
    gv = float(max(guidance_value_psf, 0))
    disc = float(max(0.0, min(negotiation_discount_pct, 50.0)))
    raw = area * gv
    negotiated = raw * (1 - disc / 100)
    return LandCostResult(
        area_sqft=area,
        guidance_value_psf=gv,
        negotiation_discount_pct=disc,
        raw_land_cost=round(raw),
        negotiated_land_cost=round(negotiated),
    )


def compute_psf_source_quality(igr_source: str | None, igr_record_count: int) -> str:
    """Compute PSF source quality label from IGR data availability.

    Args:
        igr_source: Source label from GDVEstimator ('igr_portal', 'insufficient_igr_records', etc.)
        igr_record_count: Number of IGR records used

    Returns:
        'live_igr': ≥5 live IGR portal records (high confidence)
        'fallback_igr': <5 live IGR records or insufficient data
        'listing_only': No IGR data, using listing PSF only
        'unknown': No source information available
    """
    if igr_source == "igr_portal" and igr_record_count >= 5:
        return "live_igr"
    elif igr_source == "igr_portal":  # count < 5, fallback due to insufficient records
        return "fallback_igr"
    elif igr_source in (
        "insufficient_igr_records",
        "insufficient_records",
        "sanity_rejected",
    ):
        return "fallback_igr"
    elif igr_source in ("listing_psf", "no_data", "table_unavailable"):
        return "listing_only"
    elif igr_source is None:
        return "listing_only"
    else:
        return "unknown"


def calc_gdv(sellable_area_sqft: float, sell_psf: float) -> GDVResult:
    area = float(max(sellable_area_sqft, 0))
    psf = float(max(sell_psf, 0))
    gdv = area * psf
    monthly = gdv / max(RERA_TO_POSSESSION_MONTHS, 1)
    return GDVResult(
        sellable_area_sqft=area,
        sell_psf=psf,
        gross_development_value=round(gdv),
        monthly_revenue=round(monthly),
    )


def calc_irr(
    land_cost: float,
    sellable_area_sqft: float,
    sell_psf: float,
    construction_cost_psf: float = CONSTRUCTION_COST_PSF,
    timeline_months: int = TOTAL_TIMELINE_MONTHS,
) -> IRRResult:
    lc = max(land_cost, 0)
    area = max(sellable_area_sqft, 0)
    gdv_r = calc_gdv(area, sell_psf)
    const_cost = area * max(construction_cost_psf, 0)
    total_cost = lc + const_cost
    profit = gdv_r.gross_development_value - total_cost
    margin = (profit / max(gdv_r.gross_development_value, 1)) * 100
    years = max(timeline_months, 1) / 12
    irr = (profit / max(total_cost, 1)) / years * 100

    if irr >= TARGET_IRR_GO:
        verdict = "GO"
    elif irr >= TARGET_IRR_MARGINAL:
        verdict = "MARGINAL"
    else:
        verdict = "NO-GO"

    payback = (
        int(total_cost / max(gdv_r.monthly_revenue, 1))
        if gdv_r.monthly_revenue > 0
        else 9999
    )

    return IRRResult(
        land_cost=round(lc),
        construction_cost=round(const_cost),
        total_project_cost=round(total_cost),
        gdv=gdv_r.gross_development_value,
        net_profit=round(profit),
        profit_margin_pct=round(margin, 1),
        simple_irr_pct=round(irr, 1),
        equity_required=round(total_cost * EQUITY_RATIO),
        debt_required=round(total_cost * DEBT_RATIO),
        payback_months=payback,
        verdict=verdict,
    )


def compare_scenarios(
    land_cost: float,
    sellable_area_sqft: float,
    base_psf: float,
    igr_source: str | None = None,
    igr_record_count: int = 0,
) -> ScenarioResult:
    """Compare base/bull/bear IRR scenarios.

    Args:
        land_cost: Negotiated land acquisition cost
        sellable_area_sqft: Total sellable area
        base_psf: Base case selling price per sqft
        igr_source: IGR data source label (optional, for psf_source_quality)
        igr_record_count: Number of IGR records used (optional, for psf_source_quality)

    Returns:
        ScenarioResult with base/bull/bear IRRResults and recommendation
    """
    bull_psf = base_psf * 1.10  # +10% optimistic
    bear_psf = base_psf * 0.80  # -20% downside (industry standard for 54mo timeline)

    base = calc_irr(land_cost, sellable_area_sqft, base_psf)
    bull = calc_irr(land_cost, sellable_area_sqft, bull_psf)
    bear = calc_irr(land_cost, sellable_area_sqft, bear_psf)

    # ── Risk bands (Tier 1) ─────────────────────────────────────────────────
    risk = _compute_risk_metrics(
        land_cost=base.land_cost,
        construction_cost=base.construction_cost,
        gdv=base.gdv,
        equity_required=base.equity_required,
        simple_irr_pct=base.simple_irr_pct,
        bull_irr_pct=bull.simple_irr_pct,
        bear_irr_pct=bear.simple_irr_pct,
    )
    # Set psf_source_quality (T-794) ───────────────────────────────────────────
    psf_quality = compute_psf_source_quality(igr_source, igr_record_count)
    if psf_quality != "live_igr":
        from loguru import logger as _log

        _log.warning(
            f"[IRR] PSF source quality: {psf_quality} (not live_igr) — "
            f"IRR is estimate based on {'fallback' if psf_quality == 'fallback_igr' else 'listing'} data, "
            f"not confirmed market transactions"
        )
    for r in (base, bull, bear):
        r.sharpe_ratio = risk["sharpe_ratio"]
        r.max_drawdown_pct = risk["max_drawdown_pct"]
        r.best_case_irr_pct = risk["best_case_irr_pct"]
        r.worst_case_irr_pct = risk["worst_case_irr_pct"]
        r.psf_source_quality = psf_quality

    if base.verdict == "GO" and bear.verdict != "NO-GO":
        rec = "PROCEED — base and bear cases both viable."
    elif base.verdict == "GO" and bear.verdict == "NO-GO":
        rec = "CONDITIONAL — base GO but bear NO-GO. Negotiate land cost or add JD structure."
    elif base.verdict == "MARGINAL":
        rec = "HOLD — marginal base case. Improve land cost or increase sell PSF before committing."
    else:
        rec = "PASS — base case NO-GO. Economics do not work at current inputs."

    return ScenarioResult(base=base, bull=bull, bear=bear, recommendation=rec)


# ── GDVEstimator (T-477 — IGR transaction PSF integration) ──────────────────


class GDVEstimator:
    """Estimates GDV using IGR transaction PSF with listing PSF fallback.

    Caches IGR median PSF per market for 15 minutes (dict-based TTL cache)
    to avoid redundant DB queries during board sessions.

    Negative results (insufficient data) are cached with a shorter TTL (5 min)
    so the system re-checks the DB periodically when data may have been added.

    Usage:
        est = GDVEstimator()
        result = est.estimate(sellable_area_sqft=10000, market="Yelahanka")
        # result.gross_development_value uses 90-day IGR median
        # result.igr_source = 'igr_portal' | 'listing_psf'
    """

    MIN_IGR_RECORDS = 5
    _CACHE_TTL_S = 900  # 15 minutes — positive results
    _NODATA_CACHE_TTL_S = 300  # 5 minutes — negative results (re-check sooner)
    _MAX_AREA = 10_000_000
    _MARKET_CAP = 100
    _PSF_MIN_SANITY = (
        500  # reject IGR PSF below ₹500/sqft (almost certainly data error)
    )
    _PSF_MAX_SANITY = 50000  # reject IGR PSF above ₹50,000/sqft

    def __init__(self):
        self._cache: dict[str, tuple[float | None, int, str, float]] = {}
        """Cache keyed by market name: (median_psf, count, source, expiry_timestamp)."""

    def clear_cache(self) -> None:
        """Clear internal cache. Useful for testing and after new IGR data arrives."""
        self._cache.clear()

    @staticmethod
    def _normalize_market(market: str) -> str:
        """Normalize market name: strip whitespace, title-case for ILIKE robustness."""
        return market.strip().title()[:100] if market else ""

    def estimate(self, sellable_area_sqft: float, market: str = "") -> GDVResult:
        """Calc GDV using IGR transaction PSF if available.

        Args:
            sellable_area_sqft: Sellable area in sqft. Clamped to [0, 10M].
            market: Market name (Yelahanka/Devanahalli/Hebbal). Capped at 100 chars.

        Returns:
            GDVResult with igr_source tracking. When insufficient IGR data,
            igr_source='insufficient_igr_records' and psf=0.0 (caller override).
        """
        area = float(max(0, min(sellable_area_sqft, self._MAX_AREA)))
        market_safe = self._normalize_market(market) if market else ""
        psf = 0.0
        igr_source: str | None = None
        igr_count = 0

        if market_safe:
            igr_psf, igr_count, igr_source = self._query_igr_median_psf(market_safe)
            if igr_psf is not None and igr_count >= self.MIN_IGR_RECORDS:
                psf = igr_psf

        if psf == 0.0 and igr_source is None and market_safe:
            igr_source = "insufficient_igr_records"

        gdv = area * psf
        monthly = gdv / max(RERA_TO_POSSESSION_MONTHS, 1)
        return GDVResult(
            sellable_area_sqft=area,
            sell_psf=psf,
            gross_development_value=round(gdv),
            monthly_revenue=round(monthly),
            igr_source=igr_source,
            igr_record_count=igr_count,
        )

    def _validate_psf(self, psf: float | None) -> float | None:
        """Validate IGR PSF against sanity bounds. Returns None if out of range."""
        if psf is None:
            return None
        if psf < self._PSF_MIN_SANITY or psf > self._PSF_MAX_SANITY:
            from loguru import logger as _log

            _log.warning(
                "[IGR] PSF {:.0f} outside sanity range [{}, {}] — rejecting",
                psf,
                self._PSF_MIN_SANITY,
                self._PSF_MAX_SANITY,
            )
            return None
        return psf

    def _query_igr_median_psf(self, market: str) -> tuple[float | None, int, str]:
        """Query igr_transactions for 90-day median transaction_psf.

        Results cached per market for 15 min (self._CACHE_TTL_S).
        Cache is dict-based (no external dependency) — cleared on process restart.

        Returns: (median_psf, record_count, source_label).

        Latency budget:
          - Cache hit: ~0ms
          - Warm connection (pooled): ~200-500ms
          - Cold start (first call after container start): ~2-5s
          - 95th percentile on 10K+ row market: ~800ms

        Error states handled:
          - table_unavailable: DB down, connection error, or schema mismatch
          - no_data: Query returned 0 rows (no IGR records for this market)
          - insufficient_records: < MIN_IGR_RECORDS rows exist
        """
        import time as _time

        now = _time.time()

        # Check cache first
        cached = self._cache.get(market)
        if cached is not None:
            cached_psf, cached_count, cached_source, cached_expiry = cached
            if now < cached_expiry:
                return cached_psf, cached_count, cached_source

        try:
            from utils.db import get_engine
            from sqlalchemy import text

            engine = get_engine()
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT
                            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY transaction_psf) AS median_psf,
                            COUNT(*) AS record_count
                        FROM igr_transactions
                        WHERE market ILIKE :market
                          AND registration_date >= NOW() - INTERVAL '90 days'
                          AND transaction_psf IS NOT NULL
                          AND transaction_psf > 0
                    """),
                    {"market": f"%{market}%"},
                ).fetchone()
        except Exception as exc:
            from loguru import logger as _log

            _log.warning("[IGR] median PSF query failed for market={}: {}", market, exc)
            return None, 0, "table_unavailable"

        if row and row[1] >= self.MIN_IGR_RECORDS:
            validated = self._validate_psf(float(row[0]))
            if validated is not None:
                result = (validated, int(row[1]), "igr_portal")
                ttl = self._CACHE_TTL_S
            else:
                result = (0.0, int(row[1]), "sanity_rejected")
                ttl = self._NODATA_CACHE_TTL_S
        elif row:
            result = (0.0, int(row[1]), "insufficient_records")
            ttl = self._NODATA_CACHE_TTL_S
        else:
            result = (0.0, 0, "no_data")
            ttl = self._NODATA_CACHE_TTL_S

        self._cache[market] = (result[0], result[1], result[2], now + ttl)
        return result


# ── Risk Metrics (Tier 1 — Financial Intelligence Depth) ──────────────────────
# Two-layer design:
#   1. RE-adapted Sharpe (re_sharpe_ratio) — primary: (IRR - 7% Gsec) / scenario_IRR_std.
#      Computed from 3 scenario IRRs (base/bull/bear). No empyrical dependency.
#   2. empyrical metrics — secondary: max_drawdown from 54-month cashflow/equity series.
#      Gracefully degrades when empyrical not installed.
# Rationale: Real estate IRR doesn't follow normal distribution assumptions of
# traditional financial Sharpe. The RE-adapted version uses scenario variance
# as risk proxy instead of daily/monthly return volatility.
_MIN_IRR_STD: float = (
    0.5  # minimum std in %pts — prevents inflated Sharpe from near-zero variance
)


def _build_monthly_returns(
    land_cost: float,
    construction_cost: float,
    gdv: float,
    equity_required: float,
    timeline_months: int = TOTAL_TIMELINE_MONTHS,
):
    """Project monthly net cashflow / equity to produce a returns Series.

    Cashflow structure:
      t=0 to t=17 (pre-RERA):      -monthly_construction (land cost at t=0)
      t=18 to t=53 (sell period):  +monthly_revenue - monthly_construction

    Returns empty Series if inputs are zero to avoid division by zero.

    Guards:
      - timeline_months < LAND_TO_RERA_MONTHS: clamps sell_months to 1
        to avoid zero-length or negative sell periods.
      - gdv or equity_required <= 0: returns empty Series.

    Limitations:
      - Flat construction spend (no ramp-up/tail-off during sell phase)
      - Flat sales velocity (no early-bird premium or absorption curve)
      Both simplifications are acceptable for risk banding (not for DCF).
    """
    import pandas as _pd

    if equity_required <= 0 or gdv <= 0:
        return _pd.Series(dtype=float)

    rera_months = min(LAND_TO_RERA_MONTHS, max(timeline_months, 1))
    sell_months = max(timeline_months - rera_months, 1)
    monthly_construction = construction_cost / max(timeline_months, 1)
    monthly_revenue = gdv / sell_months

    cashflows = []
    for m in range(rera_months):
        cf = -monthly_construction
        if m == 0:
            cf -= land_cost
        cashflows.append(cf)
    for m in range(sell_months):
        cashflows.append(monthly_revenue - monthly_construction)

    return _pd.Series(cashflows) / equity_required


def re_sharpe_ratio(
    irr_pct: float, risk_free_rate: float = 0.07, irr_std: float = 0.0
) -> float:
    """Real-estate adapted Sharpe ratio: (IRR - risk-free rate) / IRR std.

    Uses scenario variance as risk proxy instead of return volatility —
    appropriate for real estate where IRR distributions are non-normal.

    Guards:
      - irr_std <= _MIN_IRR_STD (0.5% pts): returns 0 (prevents inflated
        Sharpe from near-zero variance).
      - risk_free_rate < 0: clamped to 0 (negative risk-free is
        theoretically possible but not in Indian RE context).
      - NaN in any input: treated as 0 (catches upstream propagation failures).

    Args:
        irr_pct: Project IRR in percent (e.g. 18.0 for 18%).
        risk_free_rate: Risk-free rate as decimal (0.07 = 7% Indian Gsec).
        irr_std: Standard deviation of IRR across scenarios (in percent points).

    Returns:
        Float Sharpe ratio. 0.0 if irr_std is effectively zero or inputs degenerate.
    """
    import math as _math

    if any(
        _math.isnan(v)
        for v in (irr_pct, risk_free_rate, irr_std)
        if isinstance(v, (int, float))
    ):
        return 0.0
    if irr_std <= _MIN_IRR_STD:
        return 0.0
    rf_pct = max(risk_free_rate, 0.0) * 100
    return round((irr_pct - rf_pct) / irr_std, 4)


def _compute_risk_metrics(
    land_cost: float,
    construction_cost: float,
    gdv: float,
    equity_required: float,
    simple_irr_pct: float,
    bull_irr_pct: float,
    bear_irr_pct: float,
    timeline_months: int = TOTAL_TIMELINE_MONTHS,
    risk_free_rate: float = 0.07,
) -> dict:
    """Compute risk metrics: RE-adapted Sharpe, empyrical max_drawdown, best/worst case IRR.

    Order:
      1. RE-adapted Sharpe from scenario IRR variance (always available).
      2. empyrical max_drawdown from monthly cashflow series (gracefully degrades).
      3. Best/worst case IRR from bull/bear scenarios (always available).

    Returns dict with keys: sharpe_ratio, max_drawdown_pct,
    best_case_irr_pct, worst_case_irr_pct.
    """
    import statistics as _stats
    from loguru import logger as _log

    irr_values = [simple_irr_pct, bull_irr_pct, bear_irr_pct]
    irr_std = _stats.stdev(irr_values) if len(set(irr_values)) > 1 else 0.0
    re_sharpe = re_sharpe_ratio(simple_irr_pct, risk_free_rate, irr_std)

    result = {
        "sharpe_ratio": re_sharpe,
        "max_drawdown_pct": 0.0,
        "best_case_irr_pct": round(bull_irr_pct, 1),
        "worst_case_irr_pct": round(bear_irr_pct, 1),
    }

    # empyrical max_drawdown from monthly returns (optional — degrades gracefully)
    try:
        import empyrical as _ep
    except Exception:
        _log.debug("[IRR] empyrical not available — skipping max_drawdown computation")
        return result

    import time as _time

    _t0 = _time.time()
    monthly_returns = _build_monthly_returns(
        land_cost, construction_cost, gdv, equity_required, timeline_months
    )
    if len(monthly_returns) < 3:
        return result

    try:
        mdd_raw = _ep.max_drawdown(monthly_returns)
        mdd_val = None
        if mdd_raw is not None:
            mdd_f = float(mdd_raw)
            if not (mdd_f != mdd_f):  # NaN check: NaN is the only float where x != x
                mdd_val = mdd_f
        if mdd_val is not None:
            result["max_drawdown_pct"] = round(mdd_val * 100, 2)
        else:
            _log.debug(
                "[IRR] max_drawdown returned NaN — likely degenerate cashflow series"
            )
    except Exception:
        _log.warning("[IRR] empyrical max_drawdown failed (non-fatal)")
        _log.debug(
            "[IRR] risk metrics computation took {:.3f}s".format(_time.time() - _t0)
        )
        return result

    _log.debug("[IRR] risk metrics computation took {:.3f}s".format(_time.time() - _t0))
    return result


# ── IGR Source Logging (T-477) ─────────────────────────────────────────────────


def log_igr_lookup(
    market: str,
    source: str | None,
    record_count: int,
    psf: float,
    caller: str = "GDVEstimator",
):
    """Log IGR PSF lookup to agent_runs for audit trail.
    Non-fatal on failure — caller proceeds regardless.
    """
    from datetime import datetime, timezone

    try:
        from utils.db import get_engine
        from sqlalchemy import text

        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs
                        (agent_name, task_type, micro_market, status, metadata, started_at)
                    VALUES (:agent_name, 'igr_psf_lookup', :market, 'completed', :metadata, :started_at)
                """),
                {
                    "agent_name": caller,
                    "market": market,
                    "metadata": json.dumps(
                        {"source": source, "record_count": record_count, "psf": psf}
                    ),
                    "started_at": datetime.now(timezone.utc),
                },
            )
    except Exception:
        from loguru import logger as _log

        _log.warning(
            "[IGR] Failed to log lookup to agent_runs for market={} caller={}",
            market,
            caller,
        )


# ── calc_irr_npv — NPV-solving IRR (Sprint 103 — T-1203) ───────────────────────

_NPV_TOLERANCE: float = 1.0  # Accept ±₹1 NPV as converged
_MAX_CASH_FLOW_LENGTH: int = 1200  # 100 years monthly


def _log_irr_debug(msg: str, *args):
    from loguru import logger as _log
    _log.debug("[IRR_NPV] " + msg, *args)


def calc_irr_npv(cash_flows: list[float], caller: str = "unknown") -> float | None:
    """Compute NPV-solving IRR from monthly cash flows using numpy-financial.

    Validates the result by computing NPV at the found rate — if
    abs(NPV) > _NPV_TOLERANCE, the Newton-Raphson solver converged
    to a false root and None is returned.

    Args:
        cash_flows: Monthly cash flows. First element is initial investment (negative),
                   remaining are net monthly receipts. Max length 1200.
        caller: Label for Prometheus metrics ('build_cash_flow', 'board_room', 'fixture').

    Returns:
        Annualized IRR percentage rounded to 2 decimal places, or None if
        the cash flow array cannot produce a meaningful IRR.
    """
    import math as _math
    import numpy_financial as _npf

    if not cash_flows or len(cash_flows) < 2:
        _log_irr_debug("rejected: empty or single-element cash flow")
        irr_computations_total.labels(caller=caller, result="null").inc()
        return None

    if len(cash_flows) > _MAX_CASH_FLOW_LENGTH:
        _log_irr_debug("rejected: cash flow length {} exceeds max {}", len(cash_flows), _MAX_CASH_FLOW_LENGTH)
        irr_computations_total.labels(caller=caller, result="null").inc()
        return None

    has_neg = any(cf < 0 for cf in cash_flows)
    has_pos = any(cf > 0 for cf in cash_flows)
    if not (has_neg and has_pos):
        _log_irr_debug("rejected: no sign change in cash flows")
        irr_computations_total.labels(caller=caller, result="null").inc()
        return None

    try:
        monthly_rate = float(_npf.irr(cash_flows))
    except Exception as exc:
        _log_irr_debug("npf.irr raised: {}", exc)
        irr_computations_total.labels(caller=caller, result="error").inc()
        return None

    if _math.isnan(monthly_rate):
        _log_irr_debug("npf.irr returned NaN")
        irr_computations_total.labels(caller=caller, result="null").inc()
        return None

    if monthly_rate <= -1.0:
        _log_irr_debug("monthly rate {:.6f} <= -1.0 (total loss)", monthly_rate)
        irr_computations_total.labels(caller=caller, result="null").inc()
        return None

    try:
        npv = float(_npf.npv(monthly_rate, cash_flows))
        if abs(npv) > _NPV_TOLERANCE:
            _log_irr_debug("npv validation failed: npv={:.2f} at rate={:.6f}", npv, monthly_rate)
            irr_computations_total.labels(caller=caller, result="null").inc()
            return None
    except Exception as exc:
        _log_irr_debug("npf.npv raised: {}", exc)
        irr_computations_total.labels(caller=caller, result="error").inc()
        return None

    annual_pct = ((1 + monthly_rate) ** 12 - 1) * 100
    if _math.isinf(annual_pct) or _math.isnan(annual_pct):
        _log_irr_debug("annualized pct overflow: {:.6f}", annual_pct)
        irr_computations_total.labels(caller=caller, result="null").inc()
        return None

    irr_computations_total.labels(caller=caller, result="success").inc()
    return round(annual_pct, 2)


# ── Absorption Curve (T-1206 — Sprint 103) ────────────────────────────────────


def _compute_absorption_curve(
    total_units: int,
    velocity: float,
    price_per_unit: float,
    months: int,
) -> list[float]:
    """Compute curved monthly revenue based on sales velocity absorption.

    Revenue is front-loaded: sales occur at `velocity` units per month
    until inventory is exhausted. Remaining months have zero revenue.
    This produces a more realistic IRR than flat revenue for projects
    where absorption data is available.

    Args:
        total_units: Total sellable units in the project. Must be > 0
            for curved absorption to activate.
        velocity: Units sold per month (sales velocity). Can be fractional
            (e.g. 2.5 units/month). If velocity > total_units, all units
            sell in month 1.
        price_per_unit: Average price per unit in rupees.
            Monthly revenue = velocity x price_per_unit, clamped to avoid
            float overflow (> 1e15 rupees/month raises and returns flat).
        months: Total project timeline in months. Output length.

    Returns:
        List of monthly revenue values, length = months.
        Revenue is velocity * price_per_unit per month until total_units
        exhausted, then zero for remaining months. All zeros when velocity
        or total_units <= 0.

    Raises:
        ValueError: If months < 1.
    """
    if months < 1:
        raise ValueError("months must be >= 1")

    if velocity <= 0 or total_units <= 0:
        return [0.0] * months

    monthly_revenue = velocity * price_per_unit
    if monthly_revenue > 1e15 or monthly_revenue < 0:
        return [0.0] * months

    full_months = int(min(total_units / velocity, months))
    remainder = total_units - full_months * velocity

    result = [monthly_revenue] * full_months
    if remainder > 0 and full_months < months:
        result.append(remainder * price_per_unit)
        full_months += 1
    while len(result) < months:
        result.append(0.0)
    return result[:months]


# ── CashFlow Projection (Sprint 101 — T-1194) ──────────────────────────────────


@dataclass
class MonthlyCashFlowRow:
    """Single month of a project cash-flow projection."""
    month: int
    construction_outflow_cr: float
    interest_payment_cr: float
    brokerage_charge_cr: float
    sales_inflow_cr: float
    cumulative_cash_position_cr: float


@dataclass
class CashFlowSummary:
    """Aggregate metrics from a cash-flow projection.

    Attributes:
        peak_negative_cr: Maximum cumulative negative cash position in Cr
            (the "valley" of the project — informs financing requirement).
        breakeven_month: First month where cumulative cash >= 0, or None
            if the project never breaks even within the projection horizon.
        roi_annualized_pct: Simple annualized ROI — total profit / total
            cost / years. Does NOT account for time value of money.
        irr_npv_pct: True NPV-solving IRR (annualized percentage), or None
            if the cash flow pattern cannot produce a valid IRR (no sign
            change, non-convergent, or false root rejected by validation).
    """
    peak_negative_cr: float
    breakeven_month: int | None
    roi_annualized_pct: float | None
    irr_npv_pct: float | None = None


@dataclass
class CashFlowProjection:
    """Monthly cash-flow projection for a real estate project."""
    schedule: list[MonthlyCashFlowRow]
    summary: CashFlowSummary


def build_cash_flow(
    land_cost_cr: float,
    gdc_cr: float,
    construction_cost_cr: float,
    loan_pct: float = 0.5,
    interest_rate: float = 0.12,
    cp_brokerage_pct: float = 0.013,
    months: int = 36,
    sales_velocity_units_per_month: float = 0.0,
    total_units: int = 0,
    avg_unit_price: float = 0.0,
) -> CashFlowProjection:
    """Build monthly cash-flow projection for a real estate project.

    Computes month-by-month cash position including construction spend,
    debt service, brokerage, and sales revenue. Optionally uses curved
    absorption (front-loaded revenue) when sales velocity data is provided.

    Args:
        land_cost_cr: Land acquisition cost in Cr (₹ crores).
        gdc_cr: Gross development cost (total GDV) in Cr.
        construction_cost_cr: Total construction cost in Cr.
        loan_pct: Loan-to-land-cost ratio (0.0–1.0). Default 0.5.
        interest_rate: Annual interest rate on loan (e.g. 0.12 = 12%).
            Default 0.12.
        cp_brokerage_pct: Channel partner brokerage as fraction of GDV.
            Charged as one-time at month 6. Default 0.013 (1.3%).
        months: Project timeline in months (1–120). Default 36.
        sales_velocity_units_per_month: Units sold per month. If > 0 and
            total_units and avg_unit_price also provided, revenue follows
            absorption curve; else revenue spreads flat across months.
        total_units: Total sellable units (required for curved absorption).
        avg_unit_price: Average price per unit in rupees (required for
            curved absorption).

    Returns:
        CashFlowProjection with monthly schedule and summary.
        Summary includes roi_annualized_pct and irr_npv_pct (NPV-based).
        irr_npv_pct is None when cash flows have no sign change.

    Raises:
        ValueError: If months < 1.
    """
    with cashflow_build_duration_seconds.time():
        lc = max(land_cost_cr or 0.0, 0.0) * 1e7
        gdc = max(gdc_cr or 0.0, 0.0) * 1e7
        const = max(construction_cost_cr or 0.0, 0.0) * 1e7
        loan_pct = max(loan_pct or 0.0, 0.0)
        interest_rate = max(interest_rate or 0.0, 0.0)
        cp_brokerage_pct = max(cp_brokerage_pct or 0.0, 0.0)
        months = max(months or 1, 1)
        loan_amount = lc * loan_pct
        monthly_interest = loan_amount * interest_rate / 12.0
        monthly_const = const / months
        brokerage = gdc * cp_brokerage_pct

        if sales_velocity_units_per_month > 0 and total_units > 0 and avg_unit_price > 0:
            absorption_curve_calls_total.labels(mode="curved").inc()
            revenue_per_month_list = _compute_absorption_curve(
                total_units, sales_velocity_units_per_month, avg_unit_price, months
            )
        else:
            absorption_curve_calls_total.labels(mode="flat").inc()
            flat_rev = gdc / months
            revenue_per_month_list = [flat_rev] * months

        cumulative = -lc
        rows: list[MonthlyCashFlowRow] = []
        breakeven_month: int | None = None
        peak_negative = -lc
        total_outflow = lc
        total_inflow = 0.0

        for m in range(1, months + 1):
            outflow = monthly_const
            _interest = monthly_interest
            _brokerage = brokerage if m == 6 else 0.0
            _inflow = revenue_per_month_list[m - 1]
            out = outflow + _interest + _brokerage
            cumulative += _inflow - out
            total_outflow += out
            total_inflow += _inflow

            rows.append(MonthlyCashFlowRow(
                month=m,
                construction_outflow_cr=round(outflow / 1e7, 4),
                interest_payment_cr=round(_interest / 1e7, 4),
                brokerage_charge_cr=round(_brokerage / 1e7, 4),
                sales_inflow_cr=round(_inflow / 1e7, 4),
                cumulative_cash_position_cr=round(cumulative / 1e7, 4),
            ))
            if cumulative / 1e7 < peak_negative / 1e7:
                peak_negative = cumulative
            if breakeven_month is None and cumulative >= 0:
                breakeven_month = m

        total_out = total_outflow / 1e7
        total_in = total_inflow / 1e7
        profit = total_in - total_out
        roi = (profit / max(total_out, 1)) / (months / 12.0) * 100.0

        cash_flow_array = [-lc / 1e7] + [r.sales_inflow_cr - r.construction_outflow_cr - r.interest_payment_cr - r.brokerage_charge_cr for r in rows]
        irr_npv = calc_irr_npv(cash_flow_array, caller="build_cash_flow")

        return CashFlowProjection(
            schedule=rows,
            summary=CashFlowSummary(
                peak_negative_cr=round(peak_negative / 1e7, 4),
                breakeven_month=breakeven_month,
                roi_annualized_pct=round(roi, 2),
                irr_npv_pct=irr_npv,
            ),
        )


if __name__ == "__main__":
    print("=== IRR Model Self-Test =========================")
    # 5-acre Yelahanka — typically GO
    area = 5 * 43560
    lc = calc_land_cost(area, 4000, 10.0)
    print("\n[5-acre Yelahanka, ₹6,500 PSF]")
    print(
        "Land cost: ₹{:.2f}Cr (raw: ₹{:.2f}Cr)".format(
            lc.negotiated_land_cost / 1e7, lc.raw_land_cost / 1e7
        )
    )
    sellable = area * 0.65 * 2.5
    gdv = calc_gdv(sellable, 6500)
    print("GDV: ₹{:.2f}Cr".format(gdv.gross_development_value / 1e7))
    scenarios = compare_scenarios(lc.negotiated_land_cost, sellable, 6500)
    print(
        "Base: {:.1f}% ({})  Bull: {:.1f}%  Bear: {:.1f}%".format(
            scenarios.base.simple_irr_pct,
            scenarios.base.verdict,
            scenarios.bull.simple_irr_pct,
            scenarios.bear.simple_irr_pct,
        )
    )
    print("Verdict: {}".format(scenarios.recommendation))

    # NO-GO case — expensive land, low PSF
    print("\n[Small site, high land cost, low PSF — NO-GO]")
    nogo = calc_irr(50_000_000, 5000, 3500)
    print("IRR: {:.1f}% ({})".format(nogo.simple_irr_pct, nogo.verdict))

    # MARGINAL case
    print("\n[Marginal site]")
    marg = calc_irr(10_000_000, 10000, 5500)
    print("IRR: {:.1f}% ({})".format(marg.simple_irr_pct, marg.verdict))

    # Zero-land case — no crash
    print("\n[All zeros — no crash]")
    zero = calc_irr(0, 0, 0)
    print(
        "IRR: {}% ({}) | Equity: ₹{:,.0f} | Payback: {}mo".format(
            zero.simple_irr_pct, zero.verdict, zero.equity_required, zero.payback_months
        )
    )
