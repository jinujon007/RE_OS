"""
RE_OS — PSF Truth (Sprint 91 — GATE-91)

Registered-vs-ask PSF spread ("desperation index").

Computes the gap between:
- registered_transactions median PSF (ground truth, from sale deeds)
- listings median PSF (ask prices)

A wide spread means sellers are pricing above what buyers actually pay
in registered deeds — early signal of market softening or mispricing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from config.metrics import kaveri_deeds_spread_computations
from utils.db import get_engine


class SpreadResponse(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    registered_median_psf: float | None = Field(
        None, description="Median registered PSF from sale deeds"
    )
    ask_median_psf: float | None = Field(
        None, description="Median ask PSF from listings"
    )
    spread_pct: float | None = Field(
        None, description="Percentage difference (ask - registered) / registered"
    )
    n_registered: int = Field(0, description="Number of registered transactions used")
    n_listings: int = Field(0, description="Number of listings used")
    window_days: int = Field(180, description="Lookback window in days")
    status: str = Field("insufficient_data", description="ok or insufficient_data")


@dataclass
class SpreadResult:
    registered_median_psf: float | None
    ask_median_psf: float | None
    spread_pct: float | None
    n_registered: int
    n_listings: int
    window_days: int
    status: str  # "ok" | "insufficient_data"

    def __repr__(self) -> str:
        return (
            f"SpreadResult(status={self.status}, reg_psf={self.registered_median_psf}, "
            f"ask_psf={self.ask_median_psf}, spread={self.spread_pct}%, "
            f"n_reg={self.n_registered}, n_ask={self.n_listings})"
        )

    def to_dict(self) -> dict[str, Any]:
        return SpreadResponse(
            registered_median_psf=self.registered_median_psf,
            ask_median_psf=self.ask_median_psf,
            spread_pct=self.spread_pct,
            n_registered=self.n_registered,
            n_listings=self.n_listings,
            window_days=self.window_days,
            status=self.status,
        ).model_dump()

    def one_line_summary(self) -> str:
        """One-line summary for injection into Finance Head Board Room context."""
        if self.status == "insufficient_data":
            return (
                f"REGISTERED-vs-ASK SPREAD: Insufficient registered deed data "
                f"({self.n_registered} records in {self.window_days}d) — spread not computed."
            )
        if self.spread_pct == 0:
            direction = "identical"
        elif (self.spread_pct or 0) > 0:
            direction = "wider"
        else:
            direction = "narrower"
        if direction == "identical":
            return (
                f"REGISTERED-vs-ASK SPREAD: Registered median ₹{self.registered_median_psf:,.0f}/sqft "
                f"equals asking ₹{self.ask_median_psf:,.0f}/sqft — no spread. "
                f"Based on {self.n_registered} registered deeds over {self.window_days}d."
            )
        return (
            f"REGISTERED-vs-ASK SPREAD: Registered median ₹{self.registered_median_psf:,.0f}/sqft "
            f"vs asking ₹{self.ask_median_psf:,.0f}/sqft "
            f"({abs(self.spread_pct or 0):.1f}% {direction}). "
            f"Based on {self.n_registered} registered deeds over {self.window_days}d."
        )


def compute_psf_spread(
    market: str, window_days: int = 180
) -> SpreadResult:
    """Compute registered-vs-ask PSF spread for a market.

    Returns SpreadResult with registered_median_psf from registered_transactions
    and ask_median_psf from listings. Spread is calculated as
    ((ask_median - registered_median) / registered_median) * 100.

    Returns status='insufficient_data' when n_registered < 10.
    """
    engine = get_engine()
    market_clause = f"%{market}%"

    # Registered median PSF
    reg_row = None
    try:
        with engine.connect() as conn:
            # Check if table exists first (graceful degradation for pre-migration state)
            table_check = conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'registered_transactions'
                    )
                """)
            ).scalar()
            if not table_check:
                return SpreadResult(
                    registered_median_psf=None, ask_median_psf=None,
                    spread_pct=None, n_registered=0, n_listings=0,
                    window_days=window_days, status="insufficient_data",
                )
            from config.settings import SALE_DEED_TYPES as _SALE_TYPES
            reg_row = conn.execute(
                text("""
                    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY psf) AS median_psf,
                           COUNT(*) AS n
                    FROM registered_transactions
                    WHERE village ILIKE :market
                      AND psf IS NOT NULL
                      AND extraction_confidence != 'low'
                      AND reg_date >= CURRENT_DATE - :window_days * INTERVAL '1 day'
                      AND deed_type = ANY(:sale_types::text[])
                      AND consideration_inr >= 100000
                """),
                {"market": market_clause, "window_days": window_days,
                 "sale_types": list(_SALE_TYPES)},
            ).fetchone()
    except Exception:
        pass

    registered_median_psf = float(reg_row[0]) if reg_row and reg_row[0] is not None else None
    n_registered = int(reg_row[1]) if reg_row and reg_row[1] is not None else 0

    # Need at least 10 registered transactions
    if n_registered < 10:
        kaveri_deeds_spread_computations.labels(market=market, status="insufficient_data").inc()
        return SpreadResult(
            registered_median_psf=registered_median_psf,
            ask_median_psf=None,
            spread_pct=None,
            n_registered=n_registered,
            n_listings=0,
            window_days=window_days,
            status="insufficient_data",
        )

    # Ask median PSF from listings
    ask_row = None
    try:
        with engine.connect() as conn:
            ask_row = conn.execute(
                text("""
                    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY price_psf) AS median_psf,
                           COUNT(*) AS n
                    FROM listings l
                    JOIN micro_markets mm ON mm.id = l.micro_market_id
                    WHERE mm.name ILIKE :market
                      AND l.price_psf IS NOT NULL
                      AND l.price_psf > 1000
                      AND l.price_psf < 50000
                """),
                {"market": market_clause},
            ).fetchone()
    except Exception:
        pass

    ask_median_psf = float(ask_row[0]) if ask_row and ask_row[0] is not None else None
    n_listings = int(ask_row[1]) if ask_row and ask_row[1] is not None else 0

    # Compute spread
    spread_pct = None
    if registered_median_psf and registered_median_psf > 0 and ask_median_psf:
        spread_pct = round(
            ((ask_median_psf - registered_median_psf) / registered_median_psf) * 100,
            2,
        )

    kaveri_deeds_spread_computations.labels(market=market, status="ok").inc()
    return SpreadResult(
        registered_median_psf=registered_median_psf,
        ask_median_psf=ask_median_psf,
        spread_pct=spread_pct,
        n_registered=n_registered,
        n_listings=n_listings,
        window_days=window_days,
        status="ok",
    )
