{{ config(materialized='view') }}

SELECT
    m.name                                      AS micro_market,
    COUNT(r.id)                                 AS total_projects,
    SUM(r.total_units)                          AS total_units,
    SUM(r.sold_units)                           AS total_sold,
    SUM(r.unsold_units)                         AS total_unsold,
    ROUND(AVG(r.absorption_pct), 1)             AS avg_absorption_pct,
    ROUND(AVG(r.price_min_psf), 0)              AS avg_min_psf,
    ROUND(AVG(r.price_max_psf), 0)              AS avg_max_psf,
    ROUND(AVG(l_agg.avg_listing_psf), 0)        AS avg_listing_psf,
    COUNT(DISTINCT r.developer_id)              AS unique_developers
FROM {{ source('re_os', 'micro_markets') }} m
LEFT JOIN {{ source('re_os', 'rera_projects') }} r
    ON r.micro_market_id = m.id AND r.is_active = TRUE
LEFT JOIN (
    SELECT micro_market_id, AVG(price_psf) AS avg_listing_psf
    FROM {{ source('re_os', 'listings') }}
    WHERE price_psf IS NOT NULL AND price_psf > 1000 AND price_psf < 50000
    GROUP BY micro_market_id
) l_agg ON l_agg.micro_market_id = m.id
GROUP BY m.name, m.id
ORDER BY total_units DESC NULLS LAST;
