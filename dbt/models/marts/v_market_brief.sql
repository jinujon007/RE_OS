{{ config(materialized='view') }}

WITH market_agg AS (
    SELECT
        m.id                                    AS market_id,
        m.name                                  AS micro_market,
        COUNT(r.id)                             AS total_projects,
        COALESCE(SUM(r.total_units), 0)         AS total_units,
        COALESCE(SUM(r.sold_units), 0)          AS total_sold,
        COALESCE(SUM(r.unsold_units), 0)        AS total_unsold,
        ROUND(AVG(r.absorption_pct), 1)         AS avg_absorption_pct,
        ROUND(AVG(r.price_min_psf), 0)          AS avg_min_psf,
        ROUND(AVG(r.price_max_psf), 0)          AS avg_max_psf,
        ROUND(AVG(l_agg.avg_listing_psf), 0)    AS avg_listing_psf,
        ROUND(MIN(COALESCE(l_agg.avg_listing_psf * 0.85, r.price_min_psf)), 0) AS floor_psf,
        ROUND(MAX(COALESCE(l_agg.avg_listing_psf * 1.15, r.price_max_psf)), 0) AS ceiling_psf,
        COUNT(DISTINCT r.developer_id)          AS unique_developers,
        COUNT(DISTINCT CASE WHEN d.grade = 'A' THEN d.id END) AS grade_a_developers,
        COUNT(DISTINCT CASE WHEN d.grade = 'B' THEN d.id END) AS grade_b_developers,
        COUNT(CASE WHEN r.absorption_pct < 30 AND r.total_units > 100 THEN 1 END) AS low_absorption_projects,
        COUNT(CASE WHEN r.possession_date < CURRENT_DATE AND r.unsold_units > 50 THEN 1 END) AS overdue_high_unsold_projects,
        MAX(r.last_scraped_at)                  AS data_as_of
    FROM {{ source('re_os', 'micro_markets') }} m
    LEFT JOIN {{ source('re_os', 'rera_projects') }} r
        ON r.micro_market_id = m.id AND r.is_active = TRUE
    LEFT JOIN {{ source('re_os', 'developers') }} d ON r.developer_id = d.id
    LEFT JOIN (
        SELECT micro_market_id, AVG(price_psf) AS avg_listing_psf
        FROM {{ source('re_os', 'listings') }}
        WHERE price_psf IS NOT NULL AND price_psf > 1000 AND price_psf < 50000
        GROUP BY micro_market_id
    ) l_agg ON l_agg.micro_market_id = m.id
    GROUP BY m.name, m.id
),
kaveri_stats AS (
    SELECT
        kr.micro_market_id,
        COUNT(*)::NUMERIC / 12.0 AS monthly_registrations_raw,
        COUNT(*) FILTER (WHERE kr.registration_date >= CURRENT_DATE - INTERVAL '12 months')::NUMERIC
            AS registrations_12mo
    FROM {{ source('re_os', 'kaveri_registrations') }} kr
    WHERE kr.micro_market_id IS NOT NULL
    GROUP BY kr.micro_market_id
),
market_regs AS (
    SELECT
        ks.micro_market_id,
        CASE
            WHEN ks.registrations_12mo >= 3 THEN ks.registrations_12mo / 12.0
            WHEN ks.monthly_registrations_raw * 12 >= 3 THEN ks.monthly_registrations_raw
            ELSE NULL
        END AS monthly_registrations
    FROM kaveri_stats ks
),
market_fallback AS (
    SELECT
        ma.market_id,
        CASE
            WHEN COALESCE(ma.total_sold, 0) > 0
            THEN ROUND(ma.total_unsold::NUMERIC / NULLIF(ma.total_sold::NUMERIC / 36.0, 0), 1)
            ELSE NULL
        END AS mos_fallback
    FROM market_agg ma
)
SELECT
    ma.micro_market,
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
    COALESCE(
        ROUND(
            ma.total_unsold::NUMERIC
            / NULLIF(mr.monthly_registrations * 12, 0)
            * 12
        , 1),
        mf.mos_fallback
    ) AS months_of_supply,
    CASE
        WHEN mr.monthly_registrations IS NOT NULL AND ROUND(
            ma.total_unsold::NUMERIC
            / NULLIF(mr.monthly_registrations * 12, 0)
            * 12
        , 1) < 9 THEN 'UNDERSUPPLY'
        WHEN mr.monthly_registrations IS NOT NULL AND ROUND(
            ma.total_unsold::NUMERIC
            / NULLIF(mr.monthly_registrations * 12, 0)
            * 12
        , 1) <= 18 THEN 'BALANCED'
        WHEN mr.monthly_registrations IS NOT NULL THEN 'OVERSUPPLY'
        WHEN mf.mos_fallback IS NOT NULL AND mf.mos_fallback < 9 THEN 'UNDERSUPPLY'
        WHEN mf.mos_fallback IS NOT NULL AND mf.mos_fallback <= 18 THEN 'BALANCED'
        WHEN mf.mos_fallback IS NOT NULL THEN 'OVERSUPPLY'
        ELSE 'INSUFFICIENT_DATA'
    END AS supply_label,
    ma.data_as_of
FROM market_agg ma
LEFT JOIN market_regs mr ON mr.micro_market_id = ma.market_id
LEFT JOIN market_fallback mf ON mf.market_id = ma.market_id
ORDER BY ma.total_units DESC NULLS LAST;
