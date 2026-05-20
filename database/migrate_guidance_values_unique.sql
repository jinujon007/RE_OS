-- Migration: add unique constraint to guidance_values
-- Prevents duplicate guidance value records from concurrent upserts.
-- The _upsert_guidance_value() code used SELECT-then-INSERT without ON CONFLICT,
-- creating a race window for duplicates. This constraint closes it.

CREATE UNIQUE INDEX IF NOT EXISTS idx_guidance_values_unique
    ON guidance_values (micro_market_id, locality, property_type, effective_from)
    WHERE micro_market_id IS NOT NULL;
