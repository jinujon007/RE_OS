{{ config(materialized='view') }}

SELECT
    r.rera_number,
    r.project_name,
    d.name AS developer_name,
    d.grade AS developer_grade,
    m.name AS micro_market,
    r.project_type,
    r.total_units,
    r.sold_units,
    r.unsold_units,
    r.absorption_pct,
    r.price_min_psf,
    r.price_max_psf,
    r.possession_date,
    r.project_status,
    r.locality,
    r.last_scraped_at
FROM {{ source('re_os', 'rera_projects') }} r
LEFT JOIN {{ source('re_os', 'developers') }} d ON r.developer_id = d.id
LEFT JOIN {{ source('re_os', 'micro_markets') }} m ON r.micro_market_id = m.id
WHERE r.is_active = TRUE;
