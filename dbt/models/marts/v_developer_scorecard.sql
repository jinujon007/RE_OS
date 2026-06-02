{{ config(materialized='view') }}

SELECT
    d.name AS developer,
    d.grade,
    COUNT(r.id) AS total_projects,
    SUM(r.total_units) AS total_units,
    ROUND(AVG(r.absorption_pct), 1) AS avg_absorption_pct,
    COUNT(CASE WHEN r.project_status = 'Completed' THEN 1 END) AS completed,
    COUNT(CASE WHEN r.delay_months > 0 THEN 1 END) AS delayed,
    ROUND(AVG(r.delay_months), 1) AS avg_delay_months,
    STRING_AGG(DISTINCT mm.name, ', ' ORDER BY mm.name) AS markets_active_in
FROM {{ source('re_os', 'developers') }} d
LEFT JOIN {{ source('re_os', 'rera_projects') }} r ON r.developer_id = d.id
LEFT JOIN {{ source('re_os', 'micro_markets') }} mm ON r.micro_market_id = mm.id
GROUP BY d.id, d.name, d.grade
ORDER BY total_units DESC NULLS LAST;
