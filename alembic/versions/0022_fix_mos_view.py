"""Fix v_market_brief months_of_supply with 3-tier fallback + hard cap

Adds:
- Tier 1: kaveri_registrations COUNT >= 12 -> use kaveri-based formula (high confidence)
- Tier 2: COUNT < 12 and > 0 -> use kaveri formula but capped at 120 months (low confidence)
- Tier 3: COUNT = 0 -> use RERA absorption-based fallback (medium confidence)
- Hard cap LEAST(mos_raw, 120.0) on ALL calculations
- mos_quality: 'kaveri_sufficient' / 'kaveri_sparse' / 'absorption_fallback' / 'insufficient_data'
- mos_unrestricted: the raw computed value before cap (for analytical use)
- Zero-inventory markets -> NULL MoS, 'insufficient_data' quality

Migration chain:
  0021_compliance_feedback -> 0022_fix_mos_view
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0022_fix_mos_view"
down_revision: Union[str, None] = "0021_compliance_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None

_DROP_OLD = "DROP VIEW IF EXISTS v_market_brief CASCADE"

_NEW_VIEW = """
CREATE OR REPLACE VIEW v_market_brief AS
WITH market_agg AS (
    SELECT m.id AS market_id,
        m.name AS micro_market,
        count(r.id) AS total_projects,
        COALESCE(sum(r.total_units), 0::bigint) AS total_units,
        COALESCE(sum(r.sold_units), 0::bigint) AS total_sold,
        COALESCE(sum(r.unsold_units), 0::bigint) AS total_unsold,
        round(avg(r.absorption_pct), 1) AS avg_absorption_pct,
        round(avg(r.price_min_psf), 0) AS avg_min_psf,
        round(avg(r.price_max_psf), 0) AS avg_max_psf,
        round(avg(l_agg.avg_listing_psf), 0) AS avg_listing_psf,
        round(min(COALESCE(l_agg.avg_listing_psf * 0.85, r.price_min_psf)), 0) AS floor_psf,
        round(max(COALESCE(l_agg.avg_listing_psf * 1.15, r.price_max_psf)), 0) AS ceiling_psf,
        count(DISTINCT r.developer_id) AS unique_developers,
        count(DISTINCT CASE WHEN d.grade = 'A' THEN d.id END) AS grade_a_developers,
        count(DISTINCT CASE WHEN d.grade = 'B' THEN d.id END) AS grade_b_developers,
        count(CASE WHEN r.absorption_pct < 30::numeric AND r.total_units > 100 THEN 1 END) AS low_absorption_projects,
        count(CASE WHEN r.possession_date < CURRENT_DATE AND r.unsold_units > 50 THEN 1 END) AS overdue_high_unsold_projects,
        max(r.last_scraped_at) AS data_as_of
    FROM micro_markets m
    LEFT JOIN rera_projects r ON r.micro_market_id = m.id AND r.is_active = true
    LEFT JOIN developers d ON r.developer_id = d.id
    LEFT JOIN (
        SELECT listings.micro_market_id,
            avg(listings.price_psf) AS avg_listing_psf
        FROM listings
        WHERE listings.price_psf IS NOT NULL AND listings.price_psf > 1000::numeric AND listings.price_psf < 50000::numeric
        GROUP BY listings.micro_market_id
    ) l_agg ON l_agg.micro_market_id = m.id
    GROUP BY m.name, m.id
),
kaveri_stats AS (
    SELECT kr.micro_market_id,
        count(*) AS total_count,
        count(*)::numeric / 12.0 AS monthly_registrations_raw,
        count(*) FILTER (WHERE kr.registration_date >= (CURRENT_DATE - '1 year'::interval))::numeric AS registrations_12mo
    FROM kaveri_registrations kr
    WHERE kr.micro_market_id IS NOT NULL
    GROUP BY kr.micro_market_id
),
market_regs AS (
    SELECT ks.micro_market_id,
        ks.total_count,
        CASE
            WHEN ks.registrations_12mo >= 3::numeric THEN ks.registrations_12mo / 12.0
            ELSE ks.monthly_registrations_raw
        END AS monthly_registrations
    FROM kaveri_stats ks
),
market_fallback AS (
    SELECT ma.market_id,
        CASE
            WHEN ma.total_sold > 0::bigint THEN round(
                GREATEST(ma.total_unsold::numeric, 0::numeric)
                / NULLIF(
                    GREATEST(ma.total_sold::numeric, 36.0) / 36.0,
                    0::numeric
                ),
                1
            )
            ELSE NULL::numeric
        END AS mos_fallback
    FROM market_agg ma
),
mos_computation AS (
    SELECT ma.market_id,
        ma.micro_market,
        ma.total_projects,
        GREATEST(ma.total_units, 0::bigint) AS total_units,
        GREATEST(ma.total_sold, 0::bigint) AS total_sold,
        GREATEST(ma.total_unsold, 0::bigint) AS total_unsold,
        ma.avg_absorption_pct,
        ma.avg_min_psf,
        ma.avg_max_psf,
        ma.avg_listing_psf,
        COALESCE(ma.floor_psf, 0::numeric) AS floor_psf,
        COALESCE(ma.ceiling_psf, 0::numeric) AS ceiling_psf,
        ma.unique_developers,
        ma.grade_a_developers,
        ma.grade_b_developers,
        ma.low_absorption_projects,
        ma.overdue_high_unsold_projects,
        ma.data_as_of,
        mr.total_count,
        mr.monthly_registrations,
        mf.mos_fallback,
        COALESCE(round(
            GREATEST(ma.total_unsold::numeric, 0::numeric)
            / NULLIF(
                GREATEST(COALESCE(mr.monthly_registrations, 0::numeric) * 12::numeric, 1.0),
                0::numeric
            )
            * 12::numeric,
        1), mf.mos_fallback) AS mos_raw
    FROM market_agg ma
    LEFT JOIN market_regs mr ON mr.micro_market_id = ma.market_id
    LEFT JOIN market_fallback mf ON mf.market_id = ma.market_id
)
SELECT mc.micro_market,
    mc.total_projects,
    mc.total_units,
    mc.total_sold,
    mc.total_unsold,
    mc.avg_absorption_pct,
    mc.avg_min_psf,
    mc.avg_max_psf,
    mc.avg_listing_psf,
    mc.floor_psf,
    mc.ceiling_psf,
    mc.unique_developers,
    mc.grade_a_developers,
    mc.grade_b_developers,
    mc.low_absorption_projects,
    mc.overdue_high_unsold_projects,
    CASE
        WHEN mc.total_projects = 0 OR (mc.total_unsold = 0 AND mc.mos_raw IS NULL) THEN NULL::numeric
        ELSE LEAST(mc.mos_raw, 120.0)
    END AS months_of_supply,
    CASE
        WHEN mc.total_projects = 0 OR (mc.total_unsold = 0 AND mc.mos_raw IS NULL) THEN 'INSUFFICIENT_DATA'::text
        WHEN LEAST(mc.mos_raw, 120.0) < 9::numeric THEN 'UNDERSUPPLY'::text
        WHEN LEAST(mc.mos_raw, 120.0) <= 18::numeric THEN 'BALANCED'::text
        ELSE 'OVERSUPPLY'::text
    END AS supply_label,
    mc.mos_raw AS mos_unrestricted,
    CASE
        WHEN mc.total_count >= 12 THEN 'kaveri_sufficient'::text
        WHEN mc.total_count > 0 THEN 'kaveri_sparse'::text
        WHEN mc.mos_fallback IS NOT NULL THEN 'absorption_fallback'::text
        ELSE 'insufficient_data'::text
    END AS mos_quality,
    mc.data_as_of
FROM mos_computation mc
ORDER BY mc.total_units DESC NULLS LAST
"""

_ORIGINAL_VIEW = """CREATE OR REPLACE VIEW v_market_brief AS
WITH market_agg AS (
    SELECT m.id AS market_id,
        m.name AS micro_market,
        count(r.id) AS total_projects,
        COALESCE(sum(r.total_units), 0::bigint) AS total_units,
        COALESCE(sum(r.sold_units), 0::bigint) AS total_sold,
        COALESCE(sum(r.unsold_units), 0::bigint) AS total_unsold,
        round(avg(r.absorption_pct), 1) AS avg_absorption_pct,
        round(avg(r.price_min_psf), 0) AS avg_min_psf,
        round(avg(r.price_max_psf), 0) AS avg_max_psf,
        round(avg(l_agg.avg_listing_psf), 0) AS avg_listing_psf,
        round(min(COALESCE(l_agg.avg_listing_psf * 0.85, r.price_min_psf)), 0) AS floor_psf,
        round(max(COALESCE(l_agg.avg_listing_psf * 1.15, r.price_max_psf)), 0) AS ceiling_psf,
        count(DISTINCT r.developer_id) AS unique_developers,
        count(DISTINCT CASE WHEN d.grade = 'A'::bpchar THEN d.id END) AS grade_a_developers,
        count(DISTINCT CASE WHEN d.grade = 'B'::bpchar THEN d.id END) AS grade_b_developers,
        count(CASE WHEN r.absorption_pct < 30::numeric AND r.total_units > 100 THEN 1 END) AS low_absorption_projects,
        count(CASE WHEN r.possession_date < CURRENT_DATE AND r.unsold_units > 50 THEN 1 END) AS overdue_high_unsold_projects,
        max(r.last_scraped_at) AS data_as_of
    FROM micro_markets m
    LEFT JOIN rera_projects r ON r.micro_market_id = m.id AND r.is_active = true
    LEFT JOIN developers d ON r.developer_id = d.id
    LEFT JOIN (
        SELECT listings.micro_market_id,
            avg(listings.price_psf) AS avg_listing_psf
        FROM listings
        WHERE listings.price_psf IS NOT NULL AND listings.price_psf > 1000::numeric AND listings.price_psf < 50000::numeric
        GROUP BY listings.micro_market_id
    ) l_agg ON l_agg.micro_market_id = m.id
    GROUP BY m.name, m.id
),
kaveri_stats AS (
    SELECT kr.micro_market_id,
        count(*)::numeric / 12.0 AS monthly_registrations_raw,
        count(*) FILTER (WHERE kr.registration_date >= (CURRENT_DATE - '1 year'::interval))::numeric AS registrations_12mo
    FROM kaveri_registrations kr
    WHERE kr.micro_market_id IS NOT NULL
    GROUP BY kr.micro_market_id
),
market_regs AS (
    SELECT ks.micro_market_id,
        CASE
            WHEN ks.registrations_12mo >= 3::numeric THEN ks.registrations_12mo / 12.0
            WHEN (ks.monthly_registrations_raw * 12::numeric) >= 3::numeric THEN ks.monthly_registrations_raw
            ELSE NULL::numeric
        END AS monthly_registrations
    FROM kaveri_stats ks
),
market_fallback AS (
    SELECT ma_1.market_id,
        CASE
            WHEN COALESCE(ma_1.total_sold, 0::bigint) > 0 THEN round(ma_1.total_unsold::numeric / NULLIF(ma_1.total_sold::numeric / 36.0, 0::numeric), 1)
            ELSE NULL::numeric
        END AS mos_fallback
    FROM market_agg ma_1
)
SELECT ma.micro_market,
    ma.total_projects,
    ma.total_units,
    ma.total_sold,
    ma.total_unsold,
    ma.avg_absorption_pct,
    ma.avg_min_psf,
    ma.avg_max_psf,
    ma.avg_listing_psf,
    ma.floor_psf,
    ma.ceiling_psf,
    ma.unique_developers,
    ma.grade_a_developers,
    ma.grade_b_developers,
    ma.low_absorption_projects,
    ma.overdue_high_unsold_projects,
    COALESCE(round(ma.total_unsold::numeric / NULLIF(mr.monthly_registrations * 12::numeric, 0::numeric) * 12::numeric, 1), mf.mos_fallback) AS months_of_supply,
    CASE
        WHEN mr.monthly_registrations IS NOT NULL AND round(ma.total_unsold::numeric / NULLIF(mr.monthly_registrations * 12::numeric, 0::numeric) * 12::numeric, 1) < 9::numeric THEN 'UNDERSUPPLY'::text
        WHEN mr.monthly_registrations IS NOT NULL AND round(ma.total_unsold::numeric / NULLIF(mr.monthly_registrations * 12::numeric, 0::numeric) * 12::numeric, 1) <= 18::numeric THEN 'BALANCED'::text
        WHEN mr.monthly_registrations IS NOT NULL THEN 'OVERSUPPLY'::text
        WHEN mf.mos_fallback IS NOT NULL AND mf.mos_fallback < 9::numeric THEN 'UNDERSUPPLY'::text
        WHEN mf.mos_fallback IS NOT NULL AND mf.mos_fallback <= 18::numeric THEN 'BALANCED'::text
        WHEN mf.mos_fallback IS NOT NULL THEN 'OVERSUPPLY'::text
        ELSE 'INSUFFICIENT_DATA'::text
    END AS supply_label,
    ma.data_as_of
FROM market_agg ma
LEFT JOIN market_regs mr ON mr.micro_market_id = ma.market_id
LEFT JOIN market_fallback mf ON mf.market_id = ma.market_id
ORDER BY ma.total_units DESC NULLS LAST"""


def upgrade() -> None:
    op.execute(_DROP_OLD)
    op.execute(_NEW_VIEW)


def downgrade() -> None:
    op.execute(_DROP_OLD)
    op.execute(_ORIGINAL_VIEW)
