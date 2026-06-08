-- ============================================================
-- RE_OS v2 — Reference Data Seed (T-655)
-- Idempotent: DELETE+INSERT pattern for safe re-runs.
-- Micro-markets are seeded from existing schema.sql.
-- ============================================================

-- ============================================================
-- 1. AIZ (Airport Influence Zone) Height Limits
-- Idempotent: INSERT WHERE NOT EXISTS to preserve manual edits.
-- height_limit_m values verified 2026-06-08 against AAI CCZM Bengaluru
-- and OLS tables (AAI Act 1934 s.9A / ICAO Annex 14):
--   Yelahanka:   45m — Yelahanka IAF Defence Aerodrome IHS (≤5km from ARP)
--   Devanahalli: 45m — KIAL outer conical; BIAAPA practical cap 4–6 floors
--   Hebbal:     100m — HAL outer conical (~12km from HAL ARP); BDA RMP-2015 cap
-- ============================================================
INSERT INTO regulatory_zones (authority, zone_type, zone_code, zone_description, max_height_m, height_limit_m, note, dc_rules_reference)
SELECT * FROM (VALUES
    ('AAI', 'AIZ', 'AIZ-YEL', 'Yelahanka — IAF Defence Aerodrome IHS', 45.0, 45.0,
     'Yelahanka AFS IHS cap (45m within 5km of ARP). NOC from AFS Yelahanka + AAI NOCAS. Outer conical 5–9.26km.',
     'AAI Act 1934 s.9A; ICAO Annex 14 OLS'),
    ('AAI', 'AIZ', 'AIZ-DEV', 'Devanahalli — KIAL outer conical (7km from ARP)', 45.0, 45.0,
     'KIAL outer conical surface. BIAAPA restricts to 4–6 floors near approach corridors. Site-specific PTE via AAI NOCAS.',
     'AAI Act 1934 s.9A; BIAL OLS; BIAAPA Bylaws'),
    ('AAI', 'AIZ', 'AIZ-HEB', 'Hebbal — HAL outer conical (~12km from HAL ARP)', 100.0, 100.0,
     'HAL Defence Aerodrome outer conical. BDA RMP-2015 caps HAL outer conical at 100m. KIAL outer transitional (22km) cap 150m — HAL is binding.',
     'AAI Act 1934 s.9A; BDA RMP-2015; HAL NOC'),
    ('AAI', 'AIZ', 'AIZ-JKK', 'Jakkur — GFTS IHS (within 5km of Jakkur ARP)', 30.0, 30.0,
     'GFTS Jakkur IHS cap. NOC from GFTS Jakkur + AAI NOCAS. Multiple NOCs needed for KIAL overlap.',
     'AAI Act 1934 s.9A; ICAO Annex 14 OLS'),
    ('AAI', 'AIZ', 'AIZ-TSN', 'Thanisandra — HAL outer conical / holding pattern', 60.0, 60.0,
     'Under HAL holding pattern approach. Verify exact distance from HAL ARP via NOCAS.',
     'AAI Act 1934 s.9A')
) AS v (authority, zone_type, zone_code, zone_description, max_height_m, height_limit_m, note, dc_rules_reference)
WHERE NOT EXISTS (
    SELECT 1 FROM regulatory_zones rz WHERE rz.zone_code = v.zone_code
);

-- Back-fill height_limit_m for any AIZ rows inserted before migration 0026
UPDATE regulatory_zones
SET height_limit_m = max_height_m
WHERE zone_type = 'AIZ' AND height_limit_m IS NULL AND max_height_m IS NOT NULL;

-- ============================================================
-- 2. Soil Risk Zones (15 known problem zones in North Bengaluru)
-- ============================================================
CREATE TABLE IF NOT EXISTS seed_soil_zones (
    id SERIAL PRIMARY KEY,
    zone_name VARCHAR(200) NOT NULL,
    micro_market VARCHAR(100),
    soil_type VARCHAR(100),
    risk_level VARCHAR(20) NOT NULL,
    risk_description TEXT,
    bearing_capacity_kg_cm2 DECIMAL(4,2),
    water_table_depth_m DECIMAL(4,1),
    foundation_recommendation TEXT
);

DELETE FROM seed_soil_zones;
INSERT INTO seed_soil_zones (zone_name, micro_market, soil_type, risk_level, risk_description, bearing_capacity_kg_cm2, water_table_depth_m, foundation_recommendation) VALUES
    ('Yelahanka Old Town', 'Yelahanka', 'Silty Clay', 'MODERATE', 'Medium compressibility, seasonal moisture variation', 8.0, 4.5, 'Isolated footing at 2m depth'),
    ('Yelahanka NES', 'Yelahanka', 'Hard Murram', 'LOW', 'Good bearing, stable throughout year', 20.0, 8.0, 'Open foundation'),
    ('Yelahanka Satellite Town', 'Yelahanka', 'Sandy Silt', 'MODERATE', 'Uniform settlement, moderate drainage', 12.0, 5.5, 'Raft foundation recommended'),
    ('Devanahalli Town', 'Devanahalli', 'Red Laterite', 'LOW', 'Excellent bearing, low compressibility', 25.0, 10.0, 'Open foundation'),
    ('Devanahalli BIAL Periphery', 'Devanahalli', 'Mixed Fill', 'HIGH', 'Variable fill material, differential settlement risk', 5.0, 3.0, 'Pile foundation required; geotechnical investigation mandatory'),
    ('Devanahalli NH-44 Corridor', 'Devanahalli', 'Sandy Loam', 'MODERATE', 'Good drainage, moderate bearing', 15.0, 6.0, 'Isolated footing'),
    ('Hebbal Lake Area', 'Hebbal', 'Soft Clay', 'HIGH', 'Lake bed deposits, high compressibility, high water table', 4.0, 2.0, 'Pile foundation; dewatering required'),
    ('Hebbal Ring Road', 'Hebbal', 'Hard Murrum over Clay', 'MODERATE', 'Variable strata — hard top 2m, soft below', 10.0, 4.0, 'Under-reamed pile recommended'),
    ('Hebbal EST', 'Hebbal', 'Silty Sand', 'LOW', 'Good bearing, well-drained', 18.0, 7.0, 'Open foundation'),
    ('Jakkur Lake Bed', 'Jakkur', 'Soft Silty Clay', 'HIGH', 'Lake influence, high water table (1.5m), compressible', 3.5, 1.5, 'Pile foundation; mandatory soil report'),
    ('Thanisandra', 'Thanisandra', 'Sandy Clay', 'MODERATE', 'Moderate bearing, seasonal moisture', 10.0, 5.0, 'Raft foundation'),
    ('Kogilu', 'Kogilu', 'Red Earth', 'LOW', 'Good bearing, well-drained, stable', 22.0, 9.0, 'Open foundation'),
    ('Bagalur', 'Bagalur', 'Gravelly Sand', 'LOW', 'Excellent drainage, high bearing', 25.0, 11.0, 'Open foundation'),
    ('Doddaballapur Road', 'Doddaballapur Road', 'Mixed Soil', 'MODERATE', 'Variable along corridor — localized testing required', 12.0, 6.5, 'Isolated or raft based on test results'),
    ('Nandi Hills Corridor', 'Nandi Hills Corridor', 'Rock Near Surface', 'LOW', 'Hard rock at 1-3m depth, excellent bearing', 60.0, 15.0, 'Open foundation on rock; blasting may be needed');

-- ============================================================
-- 3. Developer Aliases (10 major Bengaluru developers with variants)
-- ============================================================
CREATE TABLE IF NOT EXISTS developer_aliases (
    id SERIAL PRIMARY KEY,
    canonical_name VARCHAR(200) NOT NULL,
    alias VARCHAR(200) NOT NULL,
    match_confidence DECIMAL(3,2) DEFAULT 0.9,
    UNIQUE(canonical_name, alias)
);

INSERT INTO developer_aliases (canonical_name, alias, match_confidence)
SELECT * FROM (VALUES
    ('Brigade Group', 'Brigade Enterprises', 1.0),
    ('Brigade Group', 'Brigade', 0.9),
    ('Brigade Group', 'Brigade Properties', 0.95),
    ('Prestige Group', 'Prestige Estates', 1.0),
    ('Prestige Group', 'Prestige', 0.9),
    ('Prestige Group', 'Prestige Constructions', 0.95),
    ('Sobha Limited', 'Sobha Developers', 1.0),
    ('Sobha Limited', 'Sobha', 0.9),
    ('Sobha Limited', 'Sobha Group', 0.95),
    ('Godrej Properties', 'Godrej', 0.9),
    ('Godrej Properties', 'Godrej Group', 0.95),
    ('Godrej Properties', 'Godrej Properties Ltd', 1.0),
    ('Adarsh Developers', 'Adarsh Group', 0.95),
    ('Adarsh Developers', 'Adarsh', 0.9),
    ('Salarpuria Sattva', 'Salarpuria', 0.9),
    ('Salarpuria Sattva', 'Salarpuria Group', 0.95),
    ('Salarpuria Sattva', 'Sattva Group', 0.9),
    ('Shriram Properties', 'Shriram', 0.9),
    ('Shriram Properties', 'Shriram Group', 0.95),
    ('Shriram Properties', 'Shriram Properties Ltd', 1.0),
    ('Mantri Developers', 'Mantri', 0.9),
    ('Mantri Developers', 'Mantri Group', 0.95),
    ('Puravankara Limited', 'Puravankara', 0.9),
    ('Puravankara Limited', 'Provident', 0.85),
    ('Puravankara Limited', 'Puravankara Group', 0.95),
    ('Total Environment', 'Total Environment', 1.0),
    ('Total Environment', 'TEPL', 0.85),
    ('Assetz Property', 'Assetz', 0.9),
    ('Assetz Property', 'Assetz Group', 0.95),
    ('Concorde Group', 'Concorde', 0.9),
    ('Concorde Group', 'Concorde Developers', 0.95)
) AS v (canonical_name, alias, match_confidence)
WHERE NOT EXISTS (
    SELECT 1 FROM developer_aliases da WHERE da.canonical_name = v.canonical_name AND da.alias = v.alias
);

-- ============================================================
-- 4. Regulatory Zone Extensions (BDA zone rules for North Bengaluru)
-- ============================================================
-- Only insert for markets that don't already have regulatory zones
INSERT INTO regulatory_zones (authority, zone_type, zone_code, zone_description, far_base, far_road_9m, far_road_12m, far_road_18m, far_road_24m, far_road_30m_plus, front_setback_m, side_setback_m, rear_setback_m, max_height_m, ground_coverage_pct, mixed_use_permitted, dc_rules_reference)
SELECT * FROM (VALUES
    ('BDA', 'Residential', 'R1', 'Low density residential — plotted development', 1.0, 1.0, 1.1, 1.25, 1.5, 1.75, 3.0, 1.5, 3.0, 11.5, 0.50, FALSE, 'DC Rules 2015, Clause 5.2'),
    ('BDA', 'Residential', 'R2', 'Medium density residential — apartments permitted', 1.5, 1.5, 1.75, 2.0, 2.5, 3.0, 6.0, 3.0, 6.0, 15.0, 0.45, FALSE, 'DC Rules 2015, Clause 5.3'),
    ('BDA', 'Residential', 'R3', 'High density residential — corridor development', 2.0, 2.0, 2.25, 2.5, 3.0, 3.5, 8.0, 4.0, 8.0, 18.0, 0.40, TRUE, 'DC Rules 2015, Clause 5.4'),
    ('BDA', 'Commercial', 'C1', 'Neighbourhood commercial — local shops', 1.25, 1.25, 1.5, 1.75, 2.0, 2.25, 4.0, 2.0, 4.0, 12.0, 0.50, FALSE, 'DC Rules 2015, Clause 6.1'),
    ('BDA', 'Commercial', 'C2', 'Commercial corridor — mixed development', 2.0, 2.0, 2.25, 2.5, 3.0, 3.5, 6.0, 3.0, 6.0, 18.0, 0.45, TRUE, 'DC Rules 2015, Clause 6.2'),
    ('BDA', 'Commercial', 'C3', 'Commercial core — district centre', 2.5, 2.5, 2.75, 3.0, 3.5, 4.0, 8.0, 4.0, 8.0, 24.0, 0.40, TRUE, 'DC Rules 2015, Clause 6.3'),
    ('BDA', 'Mixed Use', 'MU', 'Mixed use — residential + commercial', 2.0, 2.0, 2.25, 2.5, 3.0, 3.5, 6.0, 3.0, 6.0, 18.0, 0.45, TRUE, 'DC Rules 2015, Clause 7.1'),
    ('BDA', 'Industrial', 'I1', 'Light industrial — IT/BT parks', 1.5, 1.5, 1.75, 2.0, 2.5, 3.0, 6.0, 3.0, 6.0, 15.0, 0.40, FALSE, 'DC Rules 2015, Clause 8.1'),
    ('BBMP', 'Residential', 'R-BBMP', 'BBMP jurisdiction — R2 equivalent', 1.75, 1.75, 2.0, 2.25, 2.75, 3.25, 6.0, 3.0, 6.0, 15.0, 0.45, FALSE, 'BBMP Bye-laws 2018')
) AS v (authority, zone_type, zone_code, zone_description, far_base, far_road_9m, far_road_12m, far_road_18m, far_road_24m, far_road_30m_plus, front_setback_m, side_setback_m, rear_setback_m, max_height_m, ground_coverage_pct, mixed_use_permitted, dc_rules_reference)
WHERE NOT EXISTS (
    SELECT 1 FROM regulatory_zones rz
    WHERE rz.zone_code = v.zone_code AND rz.authority = v.authority
);

-- ============================================================
-- 5. BDA Zone Rules (setback exceptions, parking norms)
-- ============================================================
-- Parking norms by zone
CREATE TABLE IF NOT EXISTS seed_parking_norms (
    id SERIAL PRIMARY KEY,
    zone_code VARCHAR(20) NOT NULL,
    unit_type VARCHAR(50) NOT NULL,
    car_parking_required INT NOT NULL,
    two_wheeler_parking_required INT NOT NULL,
    visitor_parking_ratio DECIMAL(3,2) DEFAULT 0.1
);

DELETE FROM seed_parking_norms;
INSERT INTO seed_parking_norms (zone_code, unit_type, car_parking_required, two_wheeler_parking_required, visitor_parking_ratio) VALUES
    ('R1', '1BHK', 1, 1, 0.1),
    ('R1', '2BHK', 1, 1, 0.1),
    ('R1', '3BHK', 1, 2, 0.1),
    ('R2', '1BHK', 1, 1, 0.15),
    ('R2', '2BHK', 1, 1, 0.15),
    ('R2', '3BHK', 2, 2, 0.15),
    ('R2', '4BHK', 2, 2, 0.15),
    ('R3', '1BHK', 1, 1, 0.2),
    ('R3', '2BHK', 1, 1, 0.2),
    ('R3', '3BHK', 2, 2, 0.2),
    ('R3', '4BHK', 2, 2, 0.2),
    ('C1', 'Shop', 1, 2, 0.1),
    ('C2', 'Office', 1, 2, 0.15),
    ('C3', 'Commercial', 1, 2, 0.2),
    ('MU', 'Residential', 1, 1, 0.15),
    ('MU', 'Commercial', 1, 2, 0.15);

-- ============================================================
-- 6. Micro-markets priority update (ensure core markets are active)
-- ============================================================
UPDATE micro_markets SET priority = 1
WHERE slug IN ('yelahanka', 'devanahalli', 'hebbal', 'jakkur', 'thanisandra', 'kogilu', 'bagalur');
