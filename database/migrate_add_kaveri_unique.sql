-- ============================================================
-- RE_OS Migration: Add partial unique index on kaveri_registrations
-- Fixes silent duplicate insertion (ON CONFLICT DO NOTHING had no constraint target)
-- Only enforces uniqueness for non-empty registration_number values
-- Empty strings (fallback/sample records) remain unrestricted
--
-- Run:
--   docker compose cp database/migrate_add_kaveri_unique.sql postgres:/tmp/migrate_add_kaveri_unique.sql
--   docker compose exec postgres psql -U re_os_user -d re_os -f /tmp/migrate_add_kaveri_unique.sql
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_kaveri_reg_unique
    ON kaveri_registrations(registration_number)
    WHERE registration_number IS NOT NULL AND registration_number != '';

SELECT 'idx_kaveri_reg_unique created' AS result;
