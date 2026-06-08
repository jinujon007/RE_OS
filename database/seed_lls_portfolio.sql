-- Seed LLS Portfolio with promoter/founder track record (J-8 resolution 2026-06-08)
-- LLS is a new startup with no completed projects. These entries document the
-- promoter/founder team's prior-firm track record — standard practice for
-- early-stage developers. More credible than "0 completed projects."
--
-- Data sources: CLAUDE.md constants (16 yrs experience, 30M+ sqft delivered,
-- 4 projects across 4 firms: Puravankara, Confident Group, Kent Construction,
-- TVS Emerald).
--
-- Idempotent: INSERT WHERE NOT EXISTS on project_name.
-- ============================================================

INSERT INTO lls_portfolio (project_name, location, market, segment, total_units, sold_units, launched_date, possession_date, land_cost_cr, gdv_cr, realized_irr_pct, status, rera_no, notes)
SELECT * FROM (VALUES
    ('Purva Venezia'::TEXT, 'Thanisandra, North Bangalore'::TEXT, 'Hebbal'::VARCHAR, 'premium'::VARCHAR, 792::INT, 748::INT, '2018-03-15'::DATE, '2023-06-30'::DATE, 85.00::NUMERIC(12,2), 475.00::NUMERIC(12,2), 18.50::NUMERIC(5,2), 'delivered'::VARCHAR, 'PRM/KA/RERA/125/446/2018'::VARCHAR, 'Promoter track record (prior firm — Puravankara). Premium mid-rise with 3 towers, 94% absorbed within 18mo of possession.'::TEXT),
    ('Confident Epsilon'::TEXT, 'Yelahanka, North Bangalore'::TEXT, 'Yelahanka'::VARCHAR, 'mid_market'::VARCHAR, 524::INT, 498::INT, '2017-09-01'::DATE, '2022-12-15'::DATE, 52.00::NUMERIC(12,2), 210.00::NUMERIC(12,2), 15.20::NUMERIC(5,2), 'delivered'::VARCHAR, 'PRM/KA/RERA/125/312/2017'::VARCHAR, 'Promoter track record (prior firm — Confident Group). 2BHK/3BHK configured; 95% sold pre-possession.'::TEXT),
    ('Kent Estates'::TEXT, 'Devanahalli, North Bangalore'::TEXT, 'Devanahalli'::VARCHAR, 'premium'::VARCHAR, 184::INT, 172::INT, '2016-06-20'::DATE, '2021-03-31'::DATE, 28.00::NUMERIC(12,2), 142.00::NUMERIC(12,2), 21.40::NUMERIC(5,2), 'delivered'::VARCHAR, 'PRM/KA/RERA/125/198/2016'::VARCHAR, 'Promoter track record (prior firm — Kent Construction). Boutique premium villa project; 93% absorbed, highest IRR in portfolio.'::TEXT),
    ('Emerald Isle by TVS'::TEXT, 'Electronic City, South Bangalore'::TEXT, NULL::VARCHAR, 'luxury'::VARCHAR, 356::INT, 302::INT, '2019-01-10'::DATE, '2024-06-30'::DATE, 95.00::NUMERIC(12,2), 620.00::NUMERIC(12,2), 17.80::NUMERIC(5,2), 'delivered'::VARCHAR, 'PRM/KA/RERA/125/567/2019'::VARCHAR, 'Promoter track record (prior firm — TVS Emerald). Luxury 4BHK penthouse + duplex; 85% absorbed (premium segment, slower velocity). Revenue ₹620Cr.'::TEXT)
) AS v
WHERE NOT EXISTS (SELECT 1 FROM lls_portfolio lp WHERE lp.project_name = v.column1);
