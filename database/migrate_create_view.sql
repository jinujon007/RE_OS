-- ============================================================
-- RE_OS Migration: Create v_market_brief view
-- Single-query market brief — analyst reads this instead of 3 separate queries
-- Run: docker compose cp database/migrate_create_view.sql postgres:/tmp/migrate_create_view.sql
--      docker compose exec re_os_db psql -U re_os_user -d re_os -f /tmp/migrate_create_view.sql
-- ============================================================

-- Drop if exists (for re-runs)
DROP VIEW IF EXISTS v_market_brief;

-- Create the view
CREATE VIEW v_market_brief AS
SELECT
    m.name                                                         AS micro_market,
    COUNT(r.id)                                                    AS total_projects,
    SUM(r.total_units)                                             AS total_units,
    SUM(r.sold_units)                                              AS total_sold,
    SUM(r.unsold_units)                                            AS total_unsold,
    ROUND(AVG(r.absorption_pct), 1)                                AS avg_absorption_pct,
    ROUND(AVG(r.price_min_psf), 0)                                 AS avg_min_psf,
    ROUND(AVG(r.price_max_psf), 0)                                 AS avg_max_psf,
    COUNT(DISTINCT r.developer_id)                                 AS unique_developers,
    COUNT(DISTINCT CASE WHEN d.grade = 'A' THEN d.id END)          AS grade_a_developers,
    COUNT(DISTINCT CASE WHEN d.grade = 'B' THEN d.id END)          AS grade_b_developers,
    COUNT(CASE WHEN r.absorption_pct < 30
                    AND r.total_units > 100 THEN 1 END)            AS low_absorption_projects,
    COUNT(CASE WHEN r.possession_date < CURRENT_DATE
                    AND r.unsold_units > 50 THEN 1 END)            AS overdue_high_unsold_projects,
    ROUND(MIN(r.price_min_psf), 0)                                 AS floor_psf,
    ROUND(MAX(r.price_max_psf), 0)                                 AS ceiling_psf,
    MAX(r.last_scraped_at)                                         AS data_as_of
FROM micro_markets m
LEFT JOIN rera_projects r  ON r.micro_market_id = m.id AND r.is_active = TRUE
LEFT JOIN developers d     ON r.developer_id = d.id
GROUP BY m.name, m.id
ORDER BY total_units DESC NULLS LAST;

-- Verify
SELECT 'v_market_brief' AS view_name, COUNT(*) AS rows FROM v_market_brief;