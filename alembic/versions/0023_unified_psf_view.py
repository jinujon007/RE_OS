"""Unify v_market_brief PSF computation as 4-tier cascade (R12)

Adds:
- psf_source_tier (1-4): which tier won
- psf_source_label: 'kaveri_registration' / 'guidance_value' / 'live_listing' / 'seed_listing'
- Tier 1: median transaction PSF from kaveri_registrations (>=5 rows)
- Tier 2: median guidance value PSF from guidance_values (>=3 rows, igr_gazette/portal_scraped)
- Tier 3: AVG listing PSF from listings WHERE data_source != 'seed_estimated' (>=5 rows)
- Tier 4: AVG listing PSF from all listings (>=1 row, includes seed)

Migration chain:
   0022_fix_mos_view -> 0023_unified_psf_view
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0023_unified_psf_view"
down_revision: Union[str, None] = "0022_fix_mos_view"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None

_DROP_OLD = "DROP VIEW IF EXISTS v_market_brief CASCADE"

_NEW_VIEW = """
CREATE OR REPLACE VIEW v_market_brief AS
-- Determine winning PSF tier once per market (prevents value/label mismatch from
-- independent COALESCE chains racing against concurrent writes).
WITH psf_tier_select AS (
    SELECT m.id AS market_id,
        CASE
            WHEN (SELECT COUNT(*) FROM kaveri_registrations kr
                  WHERE kr.micro_market_id = m.id AND kr.area_sqft > 0 AND kr.transaction_amount > 0) >= 5
                THEN 1
            WHEN (SELECT COUNT(*) FROM guidance_values gv
                  WHERE gv.micro_market_id = m.id AND gv.guidance_value_psf > 0
                    AND gv.data_source IN ('igr_gazette', 'portal_scraped')) >= 3
                THEN 2
            WHEN (SELECT COUNT(*) FROM listings l
                  WHERE l.micro_market_id = m.id AND l.price_psf IS NOT NULL
                    AND l.price_psf > 1000 AND l.price_psf < 50000
                    AND l.data_source != 'seed_estimated') >= 5
                THEN 3
            WHEN (SELECT COUNT(*) FROM listings l
                  WHERE l.micro_market_id = m.id AND l.price_psf IS NOT NULL
                    AND l.price_psf > 1000 AND l.price_psf < 50000) >= 1
                THEN 4
            ELSE NULL
        END AS tier
    FROM micro_markets m
),
psf_tiers AS (
    SELECT pts.market_id,
        pts.tier AS psf_source_tier,
        CASE pts.tier
            WHEN 1 THEN 'kaveri_registration'
            WHEN 2 THEN 'guidance_value'
            WHEN 3 THEN 'live_listing'
            WHEN 4 THEN 'seed_listing'
            ELSE NULL
        END AS psf_source_label,
        CASE pts.tier
            WHEN 1 THEN (
                SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY kr.transaction_amount / NULLIF(kr.area_sqft, 0))
                FROM kaveri_registrations kr
                WHERE kr.micro_market_id = pts.market_id AND kr.area_sqft > 0 AND kr.transaction_amount > 0)
            WHEN 2 THEN (
                SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY gv.guidance_value_psf)
                FROM guidance_values gv
                WHERE gv.micro_market_id = pts.market_id AND gv.guidance_value_psf > 0
                  AND gv.data_source IN ('igr_gazette', 'portal_scraped'))
            WHEN 3 THEN (
                SELECT AVG(l.price_psf)
                FROM listings l
                WHERE l.micro_market_id = pts.market_id AND l.price_psf IS NOT NULL
                  AND l.price_psf > 1000 AND l.price_psf < 50000
                  AND l.data_source != 'seed_estimated')
            WHEN 4 THEN (
                SELECT AVG(l.price_psf)
                FROM listings l
                WHERE l.micro_market_id = pts.market_id AND l.price_psf IS NOT NULL
                  AND l.price_psf > 1000 AND l.price_psf < 50000)
            ELSE NULL
        END AS avg_listing_psf
    FROM psf_tier_select pts
),
market_agg AS (
    SELECT m.id AS market_id,
        m.name AS micro_market,
        count(r.id) AS total_projects,
        COALESCE(sum(r.total_units), 0::bigint) AS total_units,
        COALESCE(sum(r.sold_units), 0::bigint) AS total_sold,
        COALESCE(sum(r.unsold_units), 0::bigint) AS total_unsold,
        round(avg(r.absorption_pct)::numeric, 1) AS avg_absorption_pct,
        round(avg(r.price_min_psf)::numeric, 0) AS avg_min_psf,
        round(avg(r.price_max_psf)::numeric, 0) AS avg_max_psf,
        round(pt.avg_listing_psf::numeric, 0) AS avg_listing_psf,
        round(min(COALESCE(pt.avg_listing_psf * 0.85, r.price_min_psf))::numeric, 0) AS floor_psf,
        round(max(COALESCE(pt.avg_listing_psf * 1.15, r.price_max_psf))::numeric, 0) AS ceiling_psf,
        count(DISTINCT r.developer_id) AS unique_developers,
        count(DISTINCT CASE WHEN d.grade = 'A' THEN d.id END) AS grade_a_developers,
        count(DISTINCT CASE WHEN d.grade = 'B' THEN d.id END) AS grade_b_developers,
        count(CASE WHEN r.absorption_pct < 30::numeric AND r.total_units > 100 THEN 1 END) AS low_absorption_projects,
        count(CASE WHEN r.possession_date < CURRENT_DATE AND r.unsold_units > 50 THEN 1 END) AS overdue_high_unsold_projects,
        max(r.last_scraped_at) AS data_as_of,
        pt.psf_source_tier,
        pt.psf_source_label
    FROM micro_markets m
    LEFT JOIN rera_projects r ON r.micro_market_id = m.id AND r.is_active = true
    LEFT JOIN developers d ON r.developer_id = d.id
    LEFT JOIN psf_tiers pt ON pt.market_id = m.id
    GROUP BY m.name, m.id, pt.avg_listing_psf, pt.psf_source_tier, pt.psf_source_label
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
        ma.psf_source_tier,
        ma.psf_source_label,
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
    mc.data_as_of,
    mc.psf_source_tier,
    mc.psf_source_label
FROM mos_computation mc
ORDER BY mc.total_units DESC NULLS LAST
"""

_OLD_VIEW = """CREATE OR REPLACE VIEW v_market_brief AS
WITH market_agg AS (
    SELECT m.id AS market_id,
        m.name AS micro_market,
        count(r.id) AS total_projects,
        COALESCE(sum(r.total_units), 0::bigint) AS total_units,
        COALESCE(sum(r.sold_units), 0::bigint) AS total_sold,
        COALESCE(sum(r.unsold_units), 0::bigint) AS total_unsold,
        round(avg(r.absorption_pct)::numeric, 1) AS avg_absorption_pct,
        round(avg(r.price_min_psf)::numeric, 0) AS avg_min_psf,
        round(avg(r.price_max_psf)::numeric, 0) AS avg_max_psf,
        round(avg(l_agg.avg_listing_psf)::numeric, 0) AS avg_listing_psf,
        round(min(COALESCE(l_agg.avg_listing_psf * 0.85, r.price_min_psf))::numeric, 0) AS floor_psf,
        round(max(COALESCE(l_agg.avg_listing_psf * 1.15, r.price_max_psf))::numeric, 0) AS ceiling_psf,
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
ORDER BY mc.total_units DESC NULLS LAST"""


def upgrade() -> None:
    op.execute(_DROP_OLD)
    op.execute(_NEW_VIEW)


def downgrade() -> None:
    op.execute(_DROP_OLD)
    op.execute(_OLD_VIEW)
