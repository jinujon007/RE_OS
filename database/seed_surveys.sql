-- Seed surveys for GATE-47 live verification
-- Market IDs resolved via subquery — silently skips if market not found
-- Each survey_no is unique per market; ON CONFLICT on survey_no alone (not composite)
-- Use a CTE to ensure exactly one market row matched
WITH mm AS (SELECT id, name FROM micro_markets WHERE name = 'Devanahalli')
INSERT INTO surveys (id, survey_no, micro_market_id, total_area_acres, total_area_sqft, land_type, encumbrance_clear, is_aggregated, dc_conversion_status, created_at)
SELECT uuid_generate_v4(), '45/2', mm.id, 5.0, 217800.0, 'agricultural', false, false, 'pending', NOW()
FROM mm
ON CONFLICT (survey_no) DO NOTHING;

WITH mm AS (SELECT id, name FROM micro_markets WHERE name = 'Devanahalli')
INSERT INTO surveys (id, survey_no, micro_market_id, total_area_acres, total_area_sqft, land_type, encumbrance_clear, is_aggregated, dc_conversion_status, created_at)
SELECT uuid_generate_v4(), '102/1', mm.id, 3.2, 139392.0, 'agricultural', false, false, 'pending', NOW()
FROM mm
ON CONFLICT (survey_no) DO NOTHING;

WITH mm AS (SELECT id, name FROM micro_markets WHERE name = 'Devanahalli')
INSERT INTO surveys (id, survey_no, micro_market_id, total_area_acres, total_area_sqft, land_type, encumbrance_clear, is_aggregated, dc_conversion_status, created_at)
SELECT uuid_generate_v4(), '78/3', mm.id, 8.0, 348480.0, 'agricultural', true, true, 'in_progress', NOW()
FROM mm
ON CONFLICT (survey_no) DO NOTHING;

WITH mm AS (SELECT id, name FROM micro_markets WHERE name = 'Devanahalli')
INSERT INTO surveys (id, survey_no, micro_market_id, total_area_acres, total_area_sqft, land_type, encumbrance_clear, is_aggregated, dc_conversion_status, created_at)
SELECT uuid_generate_v4(), '34/5', mm.id, 2.0, 87120.0, 'residential', true, false, 'approved', NOW()
FROM mm
ON CONFLICT (survey_no) DO NOTHING;

WITH mm AS (SELECT id, name FROM micro_markets WHERE name = 'Devanahalli')
INSERT INTO surveys (id, survey_no, micro_market_id, total_area_acres, total_area_sqft, land_type, encumbrance_clear, is_aggregated, dc_conversion_status, created_at)
SELECT uuid_generate_v4(), '156/7', mm.id, 12.0, 522720.0, 'agricultural', false, false, 'pending', NOW()
FROM mm
ON CONFLICT (survey_no) DO NOTHING;
