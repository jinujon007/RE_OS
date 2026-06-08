-- RE_OS — One-time cleanup: empty-string registration numbers
-- Sprint 82 (GATE-82) — T-1095
--
-- Migration 0042 (Sprint 81) adds a CHECK constraint that prevents future
-- empty-string registration_number inserts. This cleanup handles existing rows.
-- Idempotent — safe to run multiple times.
-- Wrapped in explicit transaction for crash safety.

BEGIN;

UPDATE kaveri_registrations
SET registration_number = NULL
WHERE registration_number = '';

SELECT COUNT(*) AS remaining_empty
FROM kaveri_registrations
WHERE registration_number = '';

COMMIT;
