-- ============================================================
-- RE_OS v2 — Computed Views (T-654)
-- 6 views that replace what v1 needed 3 agents + 2 API calls to produce.
-- All views are CREATE OR REPLACE for idempotent deployment.
-- ============================================================

-- (1) v_opportunity_queue: Ranked opportunities by score, market, next_action, expiry
CREATE OR REPLACE VIEW v_opportunity_queue AS
SELECT
    os.id AS opportunity_id,
    os.survey_no,
    os.micro_market_id,
    mm.name AS micro_market,
    os.developer_id,
    d.name AS developer_name,
    os.score,
    os.irr_score,
    os.legal_score,
    os.timing_score,
    os.distress_score,
    os.exclusivity_score,
    os.best_deal_type,
    os.estimated_jd_irr,
    os.legal_risk_level,
    os.next_action,
    os.expiry_date,
    os.is_active,
    os.computed_at,
    RANK() OVER (PARTITION BY os.micro_market_id ORDER BY os.score DESC) AS market_rank,
    CASE
        WHEN os.score >= 0.80 THEN 'CRITICAL'
        WHEN os.score >= 0.60 THEN 'HOT'
        WHEN os.score >= 0.40 THEN 'WARM'
        ELSE 'COLD'
    END AS priority_label,
    CASE
        WHEN os.expiry_date IS NOT NULL AND os.expiry_date < CURRENT_DATE + INTERVAL '30 days' THEN 'EXPIRING'
        WHEN os.expiry_date IS NOT NULL AND os.expiry_date < CURRENT_DATE THEN 'EXPIRED'
        ELSE 'ACTIVE'
    END AS expiry_status,
    s.total_area_acres,
    s.land_type,
    s.dc_conversion_status,
    s.encumbrance_clear
FROM opportunity_scores os
LEFT JOIN micro_markets mm ON mm.id = os.micro_market_id
LEFT JOIN developers d ON d.id = os.developer_id
LEFT JOIN surveys s ON s.id = os.survey_id
WHERE os.is_active = TRUE
ORDER BY os.score DESC;

-- (2) v_developer_health: Rolling distress scores aggregated from multiple signals
CREATE OR REPLACE VIEW v_developer_health AS
SELECT
    d.id AS developer_id,
    d.name AS developer_name,
    d.grade,
    d.total_projects,
    d.completed_projects,
    d.delayed_projects,
    d.avg_delay_months,
    d.absorption_rate_pct,
    COALESCE(dh.health_score, 50.0) AS health_score,
    COALESCE(dh.financial_stability, 50.0) AS financial_stability,
    COALESCE(dh.project_completion_rate,
        CASE WHEN d.total_projects > 0
             THEN ROUND(d.completed_projects::DECIMAL / d.total_projects * 100, 2)
             ELSE NULL END
    ) AS computed_completion_rate,
    COALESCE(do2.distress_score, 0) AS latest_distress_score,
    do2.alert_level AS distress_alert_level,
    CASE
        WHEN COALESCE(dh.health_score, 50) >= 80 THEN 'HEALTHY'
        WHEN COALESCE(dh.health_score, 50) >= 60 THEN 'STABLE'
        WHEN COALESCE(dh.health_score, 50) >= 40 THEN 'WATCH'
        ELSE 'CRITICAL'
    END AS health_rating,
    CASE
        WHEN d.delayed_projects > 0 AND d.total_projects > 0
             THEN ROUND(d.delayed_projects::DECIMAL / d.total_projects * 100, 1)
        ELSE 0
    END AS delay_rate_pct,
    STRING_AGG(DISTINCT mm.name, ', ' ORDER BY mm.name) AS markets_active_in
FROM developers d
LEFT JOIN developer_health dh ON dh.developer_id = d.id
LEFT JOIN LATERAL (
    SELECT do2.distress_score, do2.alert_level
    FROM distressed_opps do2
    WHERE do2.developer_id = d.id AND do2.is_actioned = FALSE
    ORDER BY do2.detected_at DESC
    LIMIT 1
) do2 ON TRUE
LEFT JOIN rera_projects rp ON rp.developer_id = d.id
LEFT JOIN micro_markets mm ON mm.id = rp.micro_market_id
GROUP BY d.id, d.name, d.grade, d.total_projects, d.completed_projects,
         d.delayed_projects, d.avg_delay_months, d.absorption_rate_pct,
         dh.health_score, dh.financial_stability, dh.project_completion_rate,
         do2.distress_score, do2.alert_level
ORDER BY health_score ASC;

-- (3) v_market_pulse: PSF, months_supply, absorption_trend, sentiment per market
CREATE OR REPLACE VIEW v_market_pulse AS
WITH market_projects AS (
    SELECT
        rp.micro_market_id,
        COUNT(rp.id) AS total_projects,
        COUNT(rp.id) FILTER (WHERE rp.is_active) AS active_projects,
        SUM(rp.total_units) AS total_units,
        SUM(rp.sold_units) AS total_sold,
        SUM(rp.unsold_units) AS total_unsold,
        ROUND(AVG(rp.price_avg_psf), 0) AS avg_psf_rera,
        ROUND(AVG(rp.absorption_pct), 1) AS avg_absorption_pct
    FROM rera_projects rp
    GROUP BY rp.micro_market_id
),
listing_psf AS (
    SELECT
        l.micro_market_id,
        ROUND(AVG(l.price_psf), 0) AS avg_listing_psf,
        COUNT(l.id) AS active_listings
    FROM listings l
    WHERE l.is_active = TRUE AND l.price_psf IS NOT NULL
      AND l.price_psf > 1000 AND l.price_psf < 50000
    GROUP BY l.micro_market_id
),
igr_psf AS (
    SELECT
        it.micro_market_id,
        ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY it.consideration_amount / NULLIF(it.area_sqft, 0)))::numeric, 0) AS igr_median_psf,
        COUNT(it.id) AS igr_transaction_count
    FROM igr_transactions it
    WHERE it.registration_date >= CURRENT_DATE - INTERVAL '90 days'
      AND it.area_sqft IS NOT NULL AND it.area_sqft > 0
    GROUP BY it.micro_market_id
),
kaveri_stats AS (
    SELECT
        kr.micro_market_id,
        COUNT(*) FILTER (WHERE kr.registration_date >= CURRENT_DATE - INTERVAL '12 months')::NUMERIC / 12.0 AS monthly_registrations
    FROM kaveri_registrations kr
    WHERE kr.micro_market_id IS NOT NULL
    GROUP BY kr.micro_market_id
),
sentiment AS (
    SELECT
        na.micro_market_id,
        ROUND(AVG(na.sentiment_score)::numeric, 4) AS avg_sentiment,
        COUNT(na.id) AS news_count
    FROM news_articles na
    WHERE na.sentiment_score IS NOT NULL
      AND na.published_at >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY na.micro_market_id
),
market_computed AS (
    SELECT
        mp.micro_market_id,
        mp.total_projects,
        mp.active_projects,
        mp.total_units,
        mp.total_unsold,
        mp.avg_psf_rera,
        mp.avg_absorption_pct,
        lp.avg_listing_psf,
        igr.igr_median_psf,
        igr.igr_transaction_count,
        COALESCE(lp.avg_listing_psf, mp.avg_psf_rera) AS benchmark_psf,
        ks.monthly_registrations,
        s.avg_sentiment,
        s.news_count,
        lp.active_listings,
        CASE
            WHEN mp.total_unsold > 0 AND ks.monthly_registrations > 0
            THEN ROUND(mp.total_unsold::NUMERIC / NULLIF(ks.monthly_registrations * 12, 0) * 12, 1)
            ELSE NULL
        END AS mos
    FROM market_projects mp
    LEFT JOIN listing_psf lp ON lp.micro_market_id = mp.micro_market_id
    LEFT JOIN igr_psf igr ON igr.micro_market_id = mp.micro_market_id
    LEFT JOIN kaveri_stats ks ON ks.micro_market_id = mp.micro_market_id
    LEFT JOIN sentiment s ON s.micro_market_id = mp.micro_market_id
)
SELECT
    mm.id AS micro_market_id,
    mm.name AS micro_market,
    mc.total_projects,
    mc.active_projects,
    mc.total_units,
    mc.total_unsold,
    mc.avg_psf_rera,
    mc.avg_listing_psf,
    mc.igr_median_psf,
    mc.igr_transaction_count,
    mc.benchmark_psf,
    mc.avg_absorption_pct,
    mc.mos AS months_of_supply,
    CASE
        WHEN mc.mos IS NULL THEN 'INSUFFICIENT_DATA'
        WHEN mc.mos < 9 THEN 'UNDERSUPPLY'
        WHEN mc.mos <= 18 THEN 'BALANCED'
        ELSE 'OVERSUPPLY'
    END AS supply_label,
    mc.avg_sentiment,
    CASE
        WHEN mc.avg_sentiment > 0.2 THEN 'BULLISH'
        WHEN mc.avg_sentiment < -0.2 THEN 'BEARISH'
        ELSE 'NEUTRAL'
    END AS sentiment_label,
    mc.news_count,
    mc.active_listings,
    mc.igr_median_psf AS transaction_psf,
    CASE
        WHEN mc.avg_listing_psf IS NOT NULL AND mc.igr_median_psf IS NOT NULL AND mc.igr_median_psf > 0
        THEN ROUND((mc.avg_listing_psf - mc.igr_median_psf) / mc.igr_median_psf * 100, 1)
        ELSE NULL
    END AS listing_to_igr_gap_pct
FROM micro_markets mm
LEFT JOIN market_computed mc ON mc.micro_market_id = mm.id
ORDER BY mm.name;

-- (4) v_survey_full_picture: All known facts about a survey_no joined in one view
CREATE OR REPLACE VIEW v_survey_full_picture AS
SELECT
    s.id AS survey_id,
    s.survey_no,
    s.micro_market_id,
    mm.name AS micro_market,
    mm.slug AS market_slug,
    s.village,
    s.hobli,
    s.taluk,
    s.district,
    s.total_area_acres,
    s.total_area_sqft,
    s.land_type,
    s.ownership_type,
    s.dc_conversion_status,
    s.dc_order_no,
    s.dc_order_date,
    s.khata_no,
    s.khata_type,
    s.encumbrance_clear,
    s.is_aggregated,
    s.metadata AS survey_metadata,
    -- RTC summary
    COUNT(DISTINCT rtc.id) AS rtc_count,
    STRING_AGG(DISTINCT rtc.owner_name, '; ') AS rtc_owner_names,
    STRING_AGG(DISTINCT rtc.cultivation_status, '; ') AS rtc_cultivation_statuses,
    -- Khata details
    STRING_AGG(DISTINCT kr.khata_no || ' (' || kr.khata_type || ')', '; ') AS khata_details,
    -- Litigation summary
    COUNT(DISTINCT lit.id) AS litigation_count,
    STRING_AGG(DISTINCT lit.case_type || ': ' || lit.case_status, '; ') AS litigation_summary,
    -- Deal pipeline
    COUNT(DISTINCT d.id) FILTER (WHERE d.stage NOT IN ('closed_lost', 'closed_won')) AS active_deal_count,
    MAX(d.irr_base) FILTER (WHERE d.stage = 'agreed') AS best_agreed_irr,
    -- Opportunity score
    MAX(os.score) AS best_opportunity_score,
    os2.best_deal_type,
    os2.estimated_jd_irr,
    os2.legal_risk_level,
    os2.next_action,
    -- Regulatory context (spatial join via survey geom)
    MAX(rz.zone_code) AS zone_code,
    MAX(rz.far_base) AS far_base,
    MAX(rz.max_height_m) AS max_height_m,
    MAX(oc.constraint_types) AS overlay_constraints
FROM surveys s
LEFT JOIN micro_markets mm ON mm.id = s.micro_market_id
LEFT JOIN rtc_records rtc ON rtc.survey_id = s.id
LEFT JOIN khata_records kr ON kr.survey_id = s.id
LEFT JOIN litigations lit ON lit.survey_id = s.id
LEFT JOIN deals d ON d.survey_id = s.id
LEFT JOIN opportunity_scores os ON os.survey_id = s.id AND os.is_active = TRUE
LEFT JOIN LATERAL (
    SELECT os2.best_deal_type, os2.estimated_jd_irr, os2.legal_risk_level, os2.next_action
    FROM opportunity_scores os2
    WHERE os2.survey_id = s.id AND os2.is_active = TRUE
    ORDER BY os2.score DESC
    LIMIT 1
) os2 ON TRUE
LEFT JOIN LATERAL (
    SELECT rz2.zone_code, rz2.far_base, rz2.max_height_m
    FROM regulatory_zones rz2
    WHERE s.geom IS NOT NULL AND ST_Intersects(s.geom, rz2.geom)
    LIMIT 1
) rz ON TRUE
LEFT JOIN LATERAL (
    SELECT STRING_AGG(DISTINCT oc2.constraint_type, '; ') AS constraint_types
    FROM overlay_constraints oc2
    WHERE s.geom IS NOT NULL AND ST_Intersects(s.geom, oc2.geom)
) oc ON TRUE
GROUP BY s.id, s.survey_no, s.micro_market_id, mm.name, mm.slug,
         s.village, s.hobli, s.taluk, s.district,
         s.total_area_acres, s.total_area_sqft, s.land_type, s.ownership_type,
         s.dc_conversion_status, s.dc_order_no, s.dc_order_date,
         s.khata_no, s.khata_type, s.encumbrance_clear, s.is_aggregated, s.metadata,
         os2.best_deal_type, os2.estimated_jd_irr, os2.legal_risk_level, os2.next_action
ORDER BY s.survey_no;

-- (5) v_deal_pipeline_kanban: Deals by stage with velocity metrics
CREATE OR REPLACE VIEW v_deal_pipeline_kanban AS
SELECT
    d.id AS deal_id,
    d.deal_name,
    d.deal_type,
    d.stage,
    d.survey_no,
    mm.name AS micro_market,
    dev.name AS developer_name,
    d.area_acres,
    d.ask_psf,
    d.negotiated_price,
    d.landowner_ratio,
    d.irr_base,
    d.irr_bull,
    d.irr_bear,
    d.verdict,
    d.deal_lead,
    d.contacted_at,
    d.expected_close,
    d.closed_at,
    d.created_at,
    d.updated_at,
    -- Stage-level rank for kanban ordering
    CASE d.stage
        WHEN 'identified' THEN 1
        WHEN 'contacted' THEN 2
        WHEN 'evaluating' THEN 3
        WHEN 'negotiated' THEN 4
        WHEN 'agreed' THEN 5
        WHEN 'closed_won' THEN 6
        WHEN 'closed_lost' THEN 7
        ELSE 99
    END AS stage_order,
    -- Velocity: days in current stage
    CASE
        WHEN d.stage NOT IN ('closed_won', 'closed_lost')
        THEN EXTRACT(DAY FROM NOW() - d.updated_at)::INTEGER
        ELSE NULL
    END AS days_in_stage,
    -- Total cycle time (days from created to now or closed)
    EXTRACT(DAY FROM COALESCE(d.closed_at, NOW()) - d.created_at)::INTEGER AS cycle_days,
    -- IRR quality indicator
    CASE
        WHEN d.irr_base >= 20 THEN 'HIGH'
        WHEN d.irr_base >= 12 THEN 'MEDIUM'
        WHEN d.irr_base IS NOT NULL THEN 'LOW'
        ELSE 'UNKNOWN'
    END AS irr_quality,
    -- Urgency indicator
    CASE
        WHEN d.expected_close IS NOT NULL AND d.expected_close < NOW() + INTERVAL '30 days' THEN 'URGENT'
        WHEN d.expected_close IS NOT NULL AND d.expected_close < NOW() + INTERVAL '90 days' THEN 'UPCOMING'
        ELSE 'ON_TRACK'
    END AS urgency,
    -- Linked memos
    COUNT(dm.id) AS memo_count,
    -- Linked LLS projects
    COUNT(lp.id) FILTER (WHERE lp.project_status = 'active') AS active_lls_projects
FROM deals d
LEFT JOIN micro_markets mm ON mm.id = d.micro_market_id
LEFT JOIN developers dev ON dev.id = d.developer_id
LEFT JOIN deal_memos dm ON dm.deal_id = d.id
LEFT JOIN lls_projects lp ON lp.deal_id = d.id
GROUP BY d.id, d.deal_name, d.deal_type, d.stage, d.survey_no,
         mm.name, dev.name, d.area_acres, d.ask_psf, d.negotiated_price,
         d.landowner_ratio, d.irr_base, d.irr_bull, d.irr_bear, d.verdict,
         d.deal_lead, d.contacted_at, d.expected_close, d.closed_at,
         d.created_at, d.updated_at
ORDER BY stage_order, days_in_stage DESC;

-- (6) v_data_freshness: Last scrape per source + freshness score
CREATE OR REPLACE VIEW v_data_freshness AS
WITH source_stats AS (
    -- RERA project scrape
    SELECT
        'rera_projects' AS source_name,
        MAX(last_scraped_at) AS last_scraped_at,
        COUNT(*) AS record_count
    FROM rera_projects
    UNION ALL
    -- Portal listings
    SELECT
        'listings_' || source AS source_name,
        MAX(last_seen_at) AS last_scraped_at,
        COUNT(*) FILTER (WHERE is_active) AS record_count
    FROM listings
    GROUP BY source
    UNION ALL
    -- News articles
    SELECT
        'news_' || COALESCE(source, 'unknown') AS source_name,
        MAX(created_at) AS last_scraped_at,
        COUNT(*) AS record_count
    FROM news_articles
    GROUP BY source
    UNION ALL
    -- IGR transactions
    SELECT
        'igr_transactions' AS source_name,
        MAX(created_at) AS last_scraped_at,
        COUNT(*) AS record_count
    FROM igr_transactions
    UNION ALL
    -- Kaveri registrations
    SELECT
        'kaveri_registrations' AS source_name,
        MAX(created_at) AS last_scraped_at,
        COUNT(*) AS record_count
    FROM kaveri_registrations
    UNION ALL
    -- Guidance values
    SELECT
        'guidance_values' AS source_name,
        MAX(created_at) AS last_scraped_at,
        COUNT(*) AS record_count
    FROM guidance_values
    UNION ALL
    -- Developer data
    SELECT
        'developers' AS source_name,
        MAX(updated_at) AS last_scraped_at,
        COUNT(*) AS record_count
    FROM developers
    UNION ALL
    -- Agent runs (pipeline executions)
    SELECT
        'pipeline_' || task_type AS source_name,
        MAX(completed_at) AS last_scraped_at,
        COUNT(*) FILTER (WHERE status = 'completed') AS record_count
    FROM agent_runs
    WHERE completed_at IS NOT NULL
    GROUP BY task_type
    UNION ALL
    -- Surveys
    SELECT 'surveys', MAX(created_at)::timestamp, COUNT(*) FROM surveys
    UNION ALL
    -- RTC records
    SELECT 'rtc_records', MAX(created_at)::timestamp, COUNT(*) FROM rtc_records
    UNION ALL
    -- Litigations
    SELECT 'litigations', MAX(created_at)::timestamp, COUNT(*) FROM litigations
    UNION ALL
    -- Deals
    SELECT 'deals', MAX(updated_at)::timestamp, COUNT(*) FROM deals
    UNION ALL
    -- Ingest log
    SELECT 'ingest_log', MAX(created_at)::timestamp, COUNT(*) FROM ingest_log
)
SELECT
    source_name,
    last_scraped_at,
    record_count,
    CASE
        WHEN last_scraped_at IS NULL THEN 0.0
        WHEN last_scraped_at >= NOW() - INTERVAL '24 hours' THEN 1.0
        WHEN last_scraped_at >= NOW() - INTERVAL '72 hours' THEN 0.5
        ELSE 0.0
    END AS freshness_score,
    CASE
        WHEN last_scraped_at IS NULL THEN 'NEVER_SCRAPED'
        WHEN last_scraped_at >= NOW() - INTERVAL '24 hours' THEN 'LIVE'
        WHEN last_scraped_at >= NOW() - INTERVAL '72 hours' THEN 'AGING'
        ELSE 'STALE'
    END AS freshness_label
FROM source_stats
ORDER BY freshness_score ASC, source_name;
