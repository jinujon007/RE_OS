-- RE_OS — Seed regulatory zones for 3 primary markets
-- Maps to schema.sql `regulatory_zones` columns:
--   market   → zone_type          (e.g. 'Yelahanka')
--   zone     → zone_code          (R1/R2/C1)
--   far      → far_base           (decimal 5,2)
--   max_height_m → max_height_m   (decimal 5,2)
--   plot_coverage → ground_coverage_pct  (decimal 5,2, stored as percentage)
--   setback_front_m → front_setback_m    (decimal 5,2)
--   setback_side_m  → side_setback_m     (decimal 5,2)
--
-- Authority: BDA (Bangalore Development Authority)
-- DC Rules: BDA DC Rules 2015, Chapter 7 — Development Standards

-- Seed regulatory zones for 3 primary markets
-- Safe for both psql and SQLAlchemy execution contexts
-- Idempotent: DELETE before INSERT ensures re-runnable
-- Index: CREATE INDEX IF NOT EXISTS idx_regulatory_zones_type_code
--        ON regulatory_zones(zone_type, zone_code);
-- (zone_type + zone_code is the primary query filter in zone_risk_checker.py)

DELETE FROM regulatory_zones WHERE authority = 'BDA';

INSERT INTO regulatory_zones (
    authority, zone_type, zone_code, zone_description,
    far_base, max_height_m, ground_coverage_pct,
    front_setback_m, side_setback_m, rear_setback_m,
    mixed_use_permitted, dc_rules_reference
) VALUES
-- Yelahanka
('BDA', 'Yelahanka',   'R1', 'Residential — Low Density',
 1.75, 11, 50, 3.0, 1.5, 1.5, FALSE, 'BDA DC Rules 2015, Clause 7.3'),
('BDA', 'Yelahanka',   'R2', 'Residential — High Density',
 2.50, 18, 55, 4.5, 1.5, 1.5, FALSE, 'BDA DC Rules 2015, Clause 7.3'),
('BDA', 'Yelahanka',   'C1', 'Commercial — Core',
 2.25, 15, 60, 6.0, 3.0, 3.0, TRUE,  'BDA DC Rules 2015, Clause 7.5'),
-- Devanahalli
('BDA', 'Devanahalli', 'R1', 'Residential — Low Density',
 2.00, 14, 50, 3.0, 1.5, 1.5, FALSE, 'BDA DC Rules 2015, Clause 7.3'),
('BDA', 'Devanahalli', 'R2', 'Residential — High Density',
 3.00, 24, 60, 4.5, 1.5, 1.5, FALSE, 'BDA DC Rules 2015, Clause 7.3'),
('BDA', 'Devanahalli', 'C1', 'Commercial — Core',
 2.50, 18, 65, 6.0, 3.0, 3.0, TRUE,  'BDA DC Rules 2015, Clause 7.5'),
-- Hebbal
('BDA', 'Hebbal',      'R1', 'Residential — Low Density',
 1.75, 14, 50, 3.0, 1.5, 1.5, FALSE, 'BDA DC Rules 2015, Clause 7.3'),
('BDA', 'Hebbal',      'R2', 'Residential — High Density',
 2.75, 21, 58, 4.5, 1.5, 1.5, FALSE, 'BDA DC Rules 2015, Clause 7.3'),
('BDA', 'Hebbal',      'C1', 'Commercial — Core',
  2.50, 18, 60, 6.0, 3.0, 3.0, TRUE,  'BDA DC Rules 2015, Clause 7.5');
