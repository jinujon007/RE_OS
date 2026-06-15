"""
GATE Criteria Constants — single source of truth for all gate pass/fail bounds.

Every gate criterion boundary lives here. Tests, pipeline health checks, and
verification scripts import from this module — never hardcode a threshold.

Usage:
    from config.gate_criteria import GATE51_PSF_MIN, GATE51_PSF_MAX
    assert GATE51_PSF_MIN <= psf <= GATE51_PSF_MAX

    from config.gate_criteria import GATE55_CONFLICT_GAP_THRESHOLD
    if pct_gap > GATE55_CONFLICT_GAP_THRESHOLD:
        flag_conflict()

Conventions:
    - Constants are UPPER_SNAKE_CASE with GATE{NN}_ prefix.
    - Type annotations are provided for all values.
    - Ranges are [inclusive_min, inclusive_max] unless noted.
    - Update constants here when gate criteria are revised — all consumers align.

Adding new gates:
    1. Define the constant with a comment identifying the gate and metric.
    2. Add the import to the consuming test or module.
    3. Do NOT redefine the constant anywhere else.

Gate reference:
    GATE-51  (Sprint 40): Devanahalli PSF range
    GATE-52  (Sprint 41): News articles, listings per market, freshness endpoint
    GATE-53  (Sprint 42): IGR transaction count (or kaveri_registrations proxy)
    GATE-54  (Sprint 43): RERA projects, Kaveri guidance values
    GATE-55  (Sprint 44): Conflict detection gap threshold, min confidence
    GATE-56  (Sprint 45): V1 OFFICIALLY COMPLETE — 10 criteria simultaneously
"""

# GATE-51: Devanahalli avg_listing_psf range (portal market rate).
# Not compared against IGR guidance values (which are naturally lower).
GATE51_PSF_MIN: float = 3000.0
GATE51_PSF_MAX: float = 20000.0
GATE51_PSF_RANGE_LABEL: str = f"[{GATE51_PSF_MIN}, {GATE51_PSF_MAX}]"

# GATE-52: Minimum non-null news article count for GATE-52 pass.
GATE52_NEWS_MIN: int = 50

# GATE-52: Minimum listing rows per micro_market.
GATE52_LISTINGS_PER_MARKET: int = 30

# GATE-53: Minimum IGR transaction records (or kaveri_registrations proxy rows).
GATE53_TRANSACTION_MIN: int = 20

# GATE-54: Minimum RERA project count per market (live scraped).
GATE54_RERA_PROJECTS_MIN: int = 150

# GATE-54: Minimum guidance_value records (data_source='portal_scraped').
GATE54_GUIDANCE_VALUES_MIN: int = 5

# GATE-55: Minimum percentage gap between two numeric facts to flag as conflict.
# Facts whose numeric values differ by more than this threshold (exclusive)
# are written to agent_memories with fact_type='conflict'.
GATE55_CONFLICT_GAP_THRESHOLD: float = 20.0

# GATE-55: Minimum confidence for a memory to be considered in conflict detection.
# Facts with confidence below this threshold are excluded from join.
GATE55_MIN_CONFIDENCE: float = 0.4

# GATE-52: Minimum distinct source types in freshness endpoint for healthy data pipeline.
# Fewer than this in freshness response means multiple plugins are not running.
GATE52_FRESHNESS_MIN_SOURCES: int = 1

# Data quality SLOs (not gate-bounded, but ops-alerting thresholds).
# These are operational targets, not gate pass/fail criteria.
SLO_NEWS_FRESHNESS_HOURS: int = 24
SLO_LISTINGS_FRESHNESS_HOURS: int = 168  # 7 days (seed refresh)
SLO_RERA_FRESHNESS_HOURS: int = 48
SLO_IGR_FRESHNESS_HOURS: int = 48
SLO_KAVERI_FRESHNESS_HOURS: int = 168  # 7 days
SLO_SEED_STALE_DAYS: int = 7  # Seed listings older than this are flagged
SLO_SEED_MIN_LIVE_LISTINGS: int = (
    10  # If live scrape returns >= this, seed should be replaced
)
