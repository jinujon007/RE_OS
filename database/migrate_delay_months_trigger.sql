-- Migration: convert delay_months from GENERATED ALWAYS AS to trigger-computed
-- Apply to existing databases where the GENERATED column is already present.
-- Safe to run multiple times (CREATE OR REPLACE + IF EXISTS).

-- Step 1: drop the generated column
ALTER TABLE rera_projects DROP COLUMN IF EXISTS delay_months;

-- Step 2: add plain integer column
ALTER TABLE rera_projects ADD COLUMN IF NOT EXISTS delay_months INTEGER DEFAULT 0;

-- Step 3: back-fill existing rows
UPDATE rera_projects
SET delay_months = (actual_completion_date - possession_date) / 30
WHERE actual_completion_date IS NOT NULL
  AND possession_date IS NOT NULL
  AND actual_completion_date > possession_date;

-- Step 4: create trigger function
CREATE OR REPLACE FUNCTION fn_compute_delay_months()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.actual_completion_date IS NOT NULL AND NEW.possession_date IS NOT NULL
       AND NEW.actual_completion_date > NEW.possession_date THEN
        NEW.delay_months := (NEW.actual_completion_date - NEW.possession_date) / 30;
    ELSE
        NEW.delay_months := 0;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Step 5: create trigger (idempotent)
DROP TRIGGER IF EXISTS trg_compute_delay_months ON rera_projects;
CREATE TRIGGER trg_compute_delay_months
BEFORE INSERT OR UPDATE OF actual_completion_date, possession_date
ON rera_projects
FOR EACH ROW EXECUTE FUNCTION fn_compute_delay_months();
