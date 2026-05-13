-- RE_OS — Kaveri seed data for Yelahanka
-- 2024-25 Karnataka government guidance values + sample registrations
-- Run: docker compose exec postgres psql -U re_os_user -d re_os -f /docker-entrypoint-initdb.d/seed_kaveri_yelahanka.sql

-- ── Guidance Values ────────────────────────────────────────────────────────────
INSERT INTO guidance_values (
    micro_market_id, locality, property_type, road_type,
    guidance_value_psf, guidance_value_per_sqm, effective_from
) VALUES
    ('0a10553b-cc39-4ca0-ae83-5fc1643b912c', 'Yelahanka New Town', 'Residential', 'Main Road',   4800.00, 51667.20, '2024-04-01'),
    ('0a10553b-cc39-4ca0-ae83-5fc1643b912c', 'Yelahanka New Town', 'Residential', 'Cross Road',  4200.00, 45208.80, '2024-04-01'),
    ('0a10553b-cc39-4ca0-ae83-5fc1643b912c', 'Yelahanka New Town', 'Commercial',  'Main Road',   6500.00, 69966.00, '2024-04-01'),
    ('0a10553b-cc39-4ca0-ae83-5fc1643b912c', 'Kogilu',             'Residential', 'Main Road',   3800.00, 40917.20, '2024-04-01'),
    ('0a10553b-cc39-4ca0-ae83-5fc1643b912c', 'Singanayakanahalli', 'Residential', 'Cross Road',  3200.00, 34444.80, '2024-04-01'),
    ('0a10553b-cc39-4ca0-ae83-5fc1643b912c', 'Bagalur',            'Residential', 'Main Road',   2800.00, 30139.20, '2024-04-01'),
    ('0a10553b-cc39-4ca0-ae83-5fc1643b912c', 'Yelahanka',          'Residential', 'Main Road',   4500.00, 48438.00, '2024-04-01')
ON CONFLICT DO NOTHING;

-- ── Kaveri Registrations ───────────────────────────────────────────────────────
INSERT INTO kaveri_registrations (
    registration_number, document_number, micro_market_id,
    property_type, property_description,
    area_sqft, area_sqm,
    transaction_amount, guidance_value,
    stamp_duty_paid, registration_fee,
    buyer_name, seller_name,
    survey_number, village, hobli, taluk, district,
    transaction_date, registration_date
) VALUES
    (
        'KAR/BNG/2025/001234', 'DOC/001234',
        '0a10553b-cc39-4ca0-ae83-5fc1643b912c',
        'Apartment', '3BHK Apartment Sobha Dream Gardens',
        1450.00, 134.71,
        10150000, 6960000,
        507500, 101500,
        'Ravi Kumar', 'Sobha Limited',
        '45/2', 'Yelahanka', 'Yelahanka', 'Bangalore North', 'Bangalore Urban',
        '2025-03-15', '2025-03-18'
    ),
    (
        'KAR/BNG/2025/001567', 'DOC/001567',
        '0a10553b-cc39-4ca0-ae83-5fc1643b912c',
        'Apartment', '2BHK Apartment Prestige Lakeside',
        1050.00, 97.55,
        7140000, 4410000,
        357000, 71400,
        'Priya Sharma', 'Prestige Estates',
        '67/1', 'Yelahanka', 'Yelahanka', 'Bangalore North', 'Bangalore Urban',
        '2025-02-20', '2025-02-24'
    ),
    (
        'KAR/BNG/2025/001892', 'DOC/001892',
        '0a10553b-cc39-4ca0-ae83-5fc1643b912c',
        'Apartment', '3BHK Apartment Brigade Orchards',
        1680.00, 156.07,
        12096000, 8064000,
        604800, 120960,
        'Anand Raj', 'Brigade Enterprises',
        '23/4', 'Bagalur', 'Yelahanka', 'Bangalore North', 'Bangalore Urban',
        '2025-03-28', '2025-04-01'
    ),
    (
        'KAR/BNG/2025/002103', 'DOC/002103',
        '0a10553b-cc39-4ca0-ae83-5fc1643b912c',
        'Apartment', '2BHK Apartment Godrej Woodscape',
        980.00, 91.04,
        6272000, 4116000,
        313600, 62720,
        'Meera Pillai', 'Godrej Properties',
        '12/3', 'Kogilu', 'Yelahanka', 'Bangalore North', 'Bangalore Urban',
        '2025-01-10', '2025-01-14'
    ),
    (
        'KAR/BNG/2025/002445', 'DOC/002445',
        '0a10553b-cc39-4ca0-ae83-5fc1643b912c',
        'Apartment', '4BHK Apartment Sobha Dream Gardens',
        2200.00, 204.39,
        17160000, 10560000,
        858000, 171600,
        'Suresh Nair', 'Sobha Limited',
        '45/3', 'Yelahanka', 'Yelahanka', 'Bangalore North', 'Bangalore Urban',
        '2025-04-05', '2025-04-08'
    )
ON CONFLICT DO NOTHING;

-- Verify
SELECT
    'guidance_values' AS tbl,
    COUNT(*) AS rows
FROM guidance_values
WHERE micro_market_id = '0a10553b-cc39-4ca0-ae83-5fc1643b912c'
UNION ALL
SELECT
    'kaveri_registrations',
    COUNT(*)
FROM kaveri_registrations
WHERE micro_market_id = '0a10553b-cc39-4ca0-ae83-5fc1643b912c';

SELECT
    ROUND(AVG(transaction_amount / area_sqft), 0) AS avg_actual_psf,
    ROUND(AVG(4166.67), 0)                        AS avg_guidance_psf,
    COUNT(*)                                       AS registrations
FROM kaveri_registrations
WHERE micro_market_id = '0a10553b-cc39-4ca0-ae83-5fc1643b912c';
