"""
RE_OS — Data Quality Monitor (GATE-89)
Live data floor checks to detect scraper failures or DB wipe.

Command-query separation:
  - get_live_rera_count(market) -> int  (pure query, no side effects)
  - check_live_data_floor(market, floor) -> bool  (sends Discord alert on breach)
"""

from sqlalchemy import text as _sa_text
from utils.db import get_engine


def get_live_rera_count(market: str) -> int:
    """Return count of non-seed RERA records for a market.

    Pure query — no side effects. Returns 0 on empty result or DB error.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                _sa_text("""
                    SELECT COUNT(*)::int
                    FROM rera_projects rp
                    JOIN micro_markets mm ON mm.id = rp.micro_market_id
                    WHERE mm.name ILIKE :market
                      AND (rp.data_source IS NULL OR rp.data_source != 'seed_estimated')
                """),
                {"market": f"%{market}%"},
            ).fetchone()
        return int(row[0]) if row and row[0] else 0
    except Exception:
        return 0


def check_live_data_floor(market: str, floor: int = 50) -> bool:
    """Check if a market has enough live (non-seed) RERA records.

    Returns True if count >= floor (normal), False if below floor (alert sent).
    Has side effect: sends Discord ops alert on breach.
    """
    count = get_live_rera_count(market)
    if count < floor:
        from utils.discord_notifier import send_ops_alert
        send_ops_alert(
            "DATA_FLOOR_BREACH",
            f"{market} live RERA records below floor: {count} < {floor}",
        )
        return False
    return True
