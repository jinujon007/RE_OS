"""
RE_OS — Financial Intelligence Module (Sprint 62)
FinancialIntel.evaluate(...): computes purchase/JD/JV deal structure IRRs using
the LLS standard model. Includes CP brokerage, construction escalation, IGR PSF
source tracking, and weighted scenario ranking.

Evaluates three deal structures:
  - purchase: LLS bears 100% land + 100% construction cost
  - JD (Joint Development): landowner contributes land at ~30% share, LLS bears construction
  - JV (Joint Venture): LLS and partner split equity 50/50, shared risk

Ranking uses bear-case-first philosophy: base IRR (50%), sharpe ratio (20%),
bear-case viability (30%). Matches the Finance Head's mandate from crews/board_room.py.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from loguru import logger

from intelligence._shared import (
    __all__ as _,
    fval, sanitize_market, validate_market, MarketCache, timed_intel_query,
)

__all__ = [
    "FinancialIntel", "FinancialEvaluation", "DealScenario",
    "CPBrokerage", "ConstructionEscalation",
]

_JD_LANDOWNER_SHARE: float = 0.30
_JV_LLS_EQUITY_SHARE: float = 0.50
_CP_BROKERAGE_RATE: float = 0.02
_CONSTRUCTION_ESCALATION_ANNUAL: float = 0.05
_RERA_TO_POSSESSION_MONTHS: int = 36

_CACHE_NS = "financial_intel"

_DEFAULT_SELL_PSF: float = 5000.0


def _get_market_psf_fallback(market: str) -> float:
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT avg_listing_psf FROM v_market_brief WHERE micro_market ILIKE :m LIMIT 1"),
                {"m": "%%{}%%".format(market)},
            ).fetchone()
        if row and row[0] and float(row[0]) > 500:
            psf = float(row[0])
            logger.debug("[FinancialIntel] Market PSF fallback for {}: {}", market, psf)
            return psf
    except Exception as exc:
        logger.debug("[FinancialIntel] PSF fallback query failed for {}: {}", market, exc)
    logger.info("[FinancialIntel] Using DEFAULT PSF fallback for {}: {}", market, _DEFAULT_SELL_PSF)
    return _DEFAULT_SELL_PSF


@dataclass
class DealScenario:
    structure: str
    description: str
    land_cost: float
    total_project_cost: float
    equity_required: float
    debt_required: float
    gross_development_value: float
    simple_irr_pct: float
    profit_margin_pct: float
    payback_months: int
    verdict: str
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    peak_debt_equity_ratio: float = 0.0
    bear_irr_pct: float = 0.0

    def __str__(self) -> str:
        return (
            f"[{self.structure.upper()}] {self.simple_irr_pct:.1f}% IRR "
            f"({self.verdict}) | ₹{self.equity_required:,.0f} equity | "
            f"bear: {self.bear_irr_pct:.1f}%"
        )


@dataclass
class CPBrokerage:
    rate_pct: float
    commission_amount: float
    break_even_months: int | None = None


@dataclass
class ConstructionEscalation:
    base_cost_psf: float
    annual_escalation_pct: float
    escalated_cost_psf: float
    additional_cost: float


@dataclass
class FinancialEvaluation:
    market: str
    land_area_sqft: float
    sellable_area_sqft: float
    sell_psf: float
    collected_at: str
    market_found: bool = True

    purchase: DealScenario | None = None
    jd: DealScenario | None = None
    jv: DealScenario | None = None

    cp_brokerage: CPBrokerage | None = None
    construction_escalation: ConstructionEscalation | None = None

    best_structure: str = "purchase"
    recommendation: str = ""

    psf_source_quality: str = "unknown"
    igr_median_psf: float | None = None
    igr_record_count: int = 0

    def __str__(self) -> str:
        return (
            f"[FinancialEvaluation:{self.market}] "
            f"{self.sellable_area_sqft:,.0f} sqft @ ₹{self.sell_psf:,.0f} PSF | "
            f"Best: {self.best_structure.upper()} | "
            f"{self.recommendation[:80]}"
        )


class FinancialIntel:
    """Financial feasibility engine: purchase / JD / JV IRRs.
    Uses LLS standard assumptions from utils/irr_model.py.

    Usage:
        fe = FinancialIntel().evaluate("Yelahanka", 43560, 6500)
        print(fe.best_structure, fe.recommendation)
    """

    def __init__(self, caller: str = ""):
        self._cache = MarketCache()
        self._caller = caller or "FinancialIntel"

    def evaluate(
        self,
        market: str,
        land_area_sqft: float,
        sell_psf: float,
        guidance_value_psf: float = 4000.0,
        negotiation_discount_pct: float = 10.0,
        zone: str = "R2",
        construction_cost_psf: float = 2200.0,
    ) -> FinancialEvaluation:
        m_raw = sanitize_market(market)
        area = max(float(land_area_sqft), 0)
        psf = max(float(sell_psf), 0)

        if not m_raw or area <= 0 or psf <= 0:
            return FinancialEvaluation(
                market=m_raw or "", land_area_sqft=area, sellable_area_sqft=0,
                sell_psf=psf, collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=False, recommendation="Invalid inputs — area and PSF must be positive",
            )

        mi = validate_market(m_raw)
        if mi is None:
            return FinancialEvaluation(
                market=m_raw, land_area_sqft=area, sellable_area_sqft=0,
                sell_psf=psf, collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=False,
            )

        fe = FinancialEvaluation(
            market=mi["name"], land_area_sqft=area, sellable_area_sqft=0,
            sell_psf=psf, collected_at=datetime.now(timezone.utc).isoformat(),
            market_found=True,
        )

        try:
            from utils.fsi_calculator import calculate_fsi
            from utils.irr_model import calc_land_cost, calc_irr, EQUITY_RATIO, TOTAL_TIMELINE_MONTHS
            from utils.irr_model import compare_scenarios

            fsi_result = calculate_fsi(area, zone, efficiency=0.65, market=mi["name"])
            fe.sellable_area_sqft = fsi_result.sellable_area_sqft
            sellable = fsi_result.sellable_area_sqft

            lc = calc_land_cost(area, guidance_value_psf, negotiation_discount_pct)
            negotiated_land = lc.negotiated_land_cost

            self._load_igr_data(fe, mi)

            scenarios = compare_scenarios(negotiated_land, sellable, psf,
                                          igr_source=self._igr_source_for(fe),
                                          igr_record_count=fe.igr_record_count)

            fe.purchase = self._scenario_to_deal(
                "purchase",
                "Outright land purchase — LLS bears 100% land + construction cost",
                negotiated_land, sellable, psf, scenarios, construction_cost_psf, 1.0,
            )

            fe.jd = self._scenario_to_deal(
                "jd",
                f"Joint Development — landowner gets {_JD_LANDOWNER_SHARE:.0%} share, LLS bears construction",
                negotiated_land, sellable, psf, scenarios, construction_cost_psf,
                1.0 - _JD_LANDOWNER_SHARE,
            )

            fe.jv = self._scenario_to_deal(
                "jv",
                f"Joint Venture — LLS {_JV_LLS_EQUITY_SHARE:.0%}, partner <LLS_PARTNER> {1 - _JV_LLS_EQUITY_SHARE:.0%}",
                negotiated_land, sellable, psf, scenarios, construction_cost_psf,
                _JV_LLS_EQUITY_SHARE,
            )

            fe.cp_brokerage = self._compute_cp_brokerage(sellable, psf)
            fe.construction_escalation = self._compute_construction_escalation(
                sellable, construction_cost_psf
            )
            self._rank_and_recommend(fe)

        except Exception as exc:
            logger.warning("[{}] evaluate failed: {}", self._caller, exc)
            fe.recommendation = f"Evaluation failed: {exc}"

        return fe

    def _load_igr_data(self, fe: FinancialEvaluation, mi: dict):
        try:
            from utils.db import get_engine
            from sqlalchemy import text
            with get_engine(pool_size=2, max_overflow=1).connect() as conn:
                with timed_intel_query("financial_igr"):
                    row = conn.execute(text("""
                        SELECT
                            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY transaction_psf) AS median_psf,
                            COUNT(*) AS cnt
                        FROM igr_transactions
                        WHERE market ILIKE :m
                          AND transaction_psf IS NOT NULL
                          AND transaction_psf > 0
                          AND registration_date >= NOW() - INTERVAL '90 days'
                    """), {"m": mi["name"]}).fetchone()
                if row and row[1] and int(row[1]) >= 5:
                    fe.igr_median_psf = fval(row[0])
                    fe.igr_record_count = int(row[1])
                    fe.psf_source_quality = "live_igr"
                elif row and row[1]:
                    fe.igr_record_count = int(row[1])
                    fe.psf_source_quality = "fallback_igr"
                else:
                    fe.psf_source_quality = "listing_only"
        except Exception:
            fe.psf_source_quality = "listing_only"

    @staticmethod
    def _igr_source_for(fe: FinancialEvaluation) -> str | None:
        mapping = {"live_igr": "igr_portal", "fallback_igr": "insufficient_igr_records", "listing_only": "listing_psf"}
        return mapping.get(fe.psf_source_quality, None)

    def _scenario_to_deal(
        self, structure: str, description: str,
        land_cost: float, sellable: float, sell_psf: float,
        scenarios, construction_cost_psf: float,
        cost_multiplier: float,
    ) -> DealScenario:
        from utils.irr_model import calc_irr as _calc_irr, TOTAL_TIMELINE_MONTHS
        effective_land = land_cost * cost_multiplier
        irr = _calc_irr(effective_land, sellable, sell_psf, construction_cost_psf, TOTAL_TIMELINE_MONTHS)
        peak_de = irr.debt_required / max(irr.equity_required, 1)
        bear_psf = sell_psf * 0.80
        bear = _calc_irr(effective_land, sellable, bear_psf, construction_cost_psf, TOTAL_TIMELINE_MONTHS)
        return DealScenario(
            structure=structure, description=description,
            land_cost=irr.land_cost,
            total_project_cost=irr.total_project_cost,
            equity_required=irr.equity_required,
            debt_required=irr.debt_required,
            gross_development_value=irr.gdv,
            simple_irr_pct=irr.simple_irr_pct,
            profit_margin_pct=irr.profit_margin_pct,
            payback_months=irr.payback_months,
            verdict=irr.verdict,
            sharpe_ratio=irr.sharpe_ratio,
            max_drawdown_pct=irr.max_drawdown_pct,
            peak_debt_equity_ratio=round(peak_de, 2),
            bear_irr_pct=bear.simple_irr_pct,
        )

    def _compute_cp_brokerage(self, sellable: float, sell_psf: float) -> CPBrokerage:
        gdv = sellable * sell_psf
        commission = gdv * _CP_BROKERAGE_RATE
        monthly_rev = gdv / max(_RERA_TO_POSSESSION_MONTHS, 1)
        be = int(commission / max(monthly_rev, 1)) if monthly_rev > 0 else None
        return CPBrokerage(
            rate_pct=_CP_BROKERAGE_RATE * 100,
            commission_amount=round(commission),
            break_even_months=be,
        )

    def _compute_construction_escalation(
        self, sellable: float, base_cost_psf: float
    ) -> ConstructionEscalation:
        escalated_cost_psf = base_cost_psf * (1 + _CONSTRUCTION_ESCALATION_ANNUAL)
        additional = sellable * (escalated_cost_psf - base_cost_psf)
        return ConstructionEscalation(
            base_cost_psf=round(base_cost_psf, 2),
            annual_escalation_pct=_CONSTRUCTION_ESCALATION_ANNUAL * 100,
            escalated_cost_psf=round(escalated_cost_psf, 2),
            additional_cost=round(additional),
        )

    def _rank_and_recommend(self, fe: FinancialEvaluation):
        scenarios = [
            (fe.purchase, "purchase"),
            (fe.jd, "jd"),
            (fe.jv, "jv"),
        ]
        scored = []
        for ds, name in scenarios:
            if ds is None:
                continue
            irr_score = max(0, min(ds.simple_irr_pct / 20.0, 1.0))
            sharpe_score = max(0, min(ds.sharpe_ratio / 2.0, 1.0))
            bear_score = 1.0 if ds.bear_irr_pct >= 12.0 else (ds.bear_irr_pct / 12.0 if ds.bear_irr_pct > 0 else 0.0)
            composite = irr_score * 0.50 + sharpe_score * 0.20 + bear_score * 0.30
            scored.append((composite, ds, name))

        scored.sort(key=lambda x: x[0], reverse=True)

        if scored:
            best_score, best_ds, best_name = scored[0]
            fe.best_structure = best_name
            nogo = sum(1 for _, ds, _ in scored if ds.verdict == "NO-GO")
            all_no_go = all(ds.verdict == "NO-GO" for _, ds, _ in scored)

            if all_no_go:
                fe.recommendation = (
                    "PASS — all structures NO-GO. "
                    "Economics do not work at current inputs."
                )
            elif nogo == 0 and best_score > 0.7:
                fe.recommendation = (
                    f"PROCEED — all structures viable. "
                    f"Best: {best_name.upper()} ({best_ds.simple_irr_pct:.1f}% IRR, "
                    f"₹{best_ds.equity_required:,.0f} equity, bear {best_ds.bear_irr_pct:.1f}%)"
                )
            elif best_ds.verdict in ("GO", "MARGINAL"):
                fe.recommendation = (
                    f"CONDITIONAL — {best_name.upper()} viable ({best_ds.simple_irr_pct:.1f}% IRR). "
                    f"{nogo} structure(s) NO-GO — prefer {best_name.upper()}"
                )
            else:
                fe.recommendation = (
                    f"HOLD — best structure {best_name.upper()} at {best_ds.simple_irr_pct:.1f}% IRR. "
                    f"Improve land cost or sell PSF before committing."
                )
        else:
            fe.recommendation = "PASS — no viable deal structures identified."


if __name__ == "__main__":
    import json
    fe = FinancialIntel(caller="self_test").evaluate("Yelahanka", 43560, 6500)
    print(json.dumps({
        "market": fe.market,
        "market_found": fe.market_found,
        "sellable": fe.sellable_area_sqft,
        "best": fe.best_structure,
        "purchase_irr": fe.purchase.simple_irr_pct if fe.purchase else None,
        "jd_irr": fe.jd.simple_irr_pct if fe.jd else None,
        "jv_irr": fe.jv.simple_irr_pct if fe.jv else None,
        "recommendation": fe.recommendation,
        "psf_source": fe.psf_source_quality,
    }, indent=2, default=str))
