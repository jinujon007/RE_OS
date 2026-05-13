-- ============================================================
-- RE_OS Migration: Add data_source column
-- Tracks provenance of every row — portal_scraped vs seed_estimated
-- Run: docker compose cp database/migrate_data_source.sql postgres:/tmp/migrate_data_source.sql
--      docker compose exec re_os_db psql -U re_os_user -d re_os -f /tmp/migrate_data_source.sql
-- ============================================================

-- rera_projects: was this row scraped from the RERA portal or seeded manually?
ALTER TABLE rera_projects
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated'
    CHECK (data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry'));

-- kaveri_registrations: was this a real Kaveri portal record or a seed?
ALTER TABLE kaveri_registrations
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated'
    CHECK (data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry'));

-- guidance_values: government circle rates (portal vs seeded)
ALTER TABLE guidance_values
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated'
    CHECK (data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry'));

-- listings: portal listings vs sample data
ALTER TABLE listings
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated'
    CHECK (data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry'));

-- All existing rows are seed data — mark them explicitly
UPDATE rera_projects SET data_source = 'seed_estimated' WHERE data_source = 'seed_estimated';
UPDATE kaveri_registrations SET data_source = 'seed_estimated' WHERE data_source = 'seed_estimated';
UPDATE guidance_values SET data_source = 'seed_estimated' WHERE data_source = 'seed_estimated';
UPDATE listings SET data_source = 'seed_estimated' WHERE data_source = 'seed_estimated';

-- Verify
SELECT
    'rera_projects' AS table_name,
    data_source,
    COUNT(*) AS rows
FROM rera_projects
GROUP BY data_source
UNION ALL
SELECT
    'kaveri_registrations',
    data_source,
    COUNT(*)
FROM kaveri_registrations
GROUP BY data_source
UNION ALL
SELECT
    'guidance_values',
    data_source,
    COUNT(*)
FROM guidance_values
GROUP BY data_source;
