-- Seed accessibility_scores with 2026 Bengaluru travel times
-- 3 markets x 5 employment hubs = 15 rows
-- accessibility_score per row = weight * (1.0 - min(travel_min/60.0, 1.0))
-- Safe to re-run: ON CONFLICT uses timezone-aware IST date cast to match
-- the unique constraint defined in migration 0037.

INSERT INTO accessibility_scores (market, destination_name, travel_time_min, distance_km, mode, measured_at, accessibility_score) VALUES

-- Yelahanka
('Yelahanka', 'Manyata Tech Park',  25.0, 14.0, 'driving', NOW(), ROUND(0.30 * (1.0 - LEAST(25.0/60.0, 1.0)), 4)),
('Yelahanka', 'BIAL',               30.0, 20.0, 'driving', NOW(), ROUND(0.25 * (1.0 - LEAST(30.0/60.0, 1.0)), 4)),
('Yelahanka', 'Hebbal ORR',         28.0, 16.0, 'driving', NOW(), ROUND(0.20 * (1.0 - LEAST(28.0/60.0, 1.0)), 4)),
('Yelahanka', 'Whitefield ITPB',    55.0, 34.0, 'driving', NOW(), ROUND(0.15 * (1.0 - LEAST(55.0/60.0, 1.0)), 4)),
('Yelahanka', 'Nagawara',           22.0, 12.0, 'driving', NOW(), ROUND(0.10 * (1.0 - LEAST(22.0/60.0, 1.0)), 4)),

-- Devanahalli
('Devanahalli', 'Manyata Tech Park',  45.0, 32.0, 'driving', NOW(), ROUND(0.30 * (1.0 - LEAST(45.0/60.0, 1.0)), 4)),
('Devanahalli', 'BIAL',               15.0,  8.0, 'driving', NOW(), ROUND(0.25 * (1.0 - LEAST(15.0/60.0, 1.0)), 4)),
('Devanahalli', 'Hebbal ORR',         48.0, 36.0, 'driving', NOW(), ROUND(0.20 * (1.0 - LEAST(48.0/60.0, 1.0)), 4)),
('Devanahalli', 'Whitefield ITPB',    70.0, 52.0, 'driving', NOW(), ROUND(0.15 * (1.0 - LEAST(70.0/60.0, 1.0)), 4)),
('Devanahalli', 'Nagawara',           42.0, 30.0, 'driving', NOW(), ROUND(0.10 * (1.0 - LEAST(42.0/60.0, 1.0)), 4)),

-- Hebbal
('Hebbal', 'Manyata Tech Park',  18.0,  8.0, 'driving', NOW(), ROUND(0.30 * (1.0 - LEAST(18.0/60.0, 1.0)), 4)),
('Hebbal', 'BIAL',               38.0, 28.0, 'driving', NOW(), ROUND(0.25 * (1.0 - LEAST(38.0/60.0, 1.0)), 4)),
('Hebbal', 'Hebbal ORR',         10.0,  4.0, 'driving', NOW(), ROUND(0.20 * (1.0 - LEAST(10.0/60.0, 1.0)), 4)),
('Hebbal', 'Whitefield ITPB',    45.0, 26.0, 'driving', NOW(), ROUND(0.15 * (1.0 - LEAST(45.0/60.0, 1.0)), 4)),
('Hebbal', 'Nagawara',           15.0,  6.0, 'driving', NOW(), ROUND(0.10 * (1.0 - LEAST(15.0/60.0, 1.0)), 4))

ON CONFLICT (market, destination_name, mode, (measured_at AT TIME ZONE 'Asia/Kolkata')::DATE) DO NOTHING;
