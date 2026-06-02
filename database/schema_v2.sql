-- ============================================================
-- RE_OS v2 — Complete Data Model
-- 2026-06-02 | Sprint 60 | GATE-44
--
-- PRE-FLIGHT INDEX SPEC (T-709 — v2 Index Pre-flight Audit)
-- ============================================================
-- Path 1: distressed_dev_scan
--   Query: rera_projects WHERE micro_market_id=? AND project_status NOT IN (...)
--          AND possession_date < NOW() AND developer has <5 total projects
--   Index: idx_rera_projects_distressed ON rera_projects(micro_market_id, project_status, possession_date)
--   Rationale: Composite B+Tree covers all 3 filter columns. Without this, PG
--     does bitmap heap scan on 700+ rows per market. Partial NOT IN excluded.
--   Note: possession_date used as proxy for expected_completion column.
--
-- Path 2: active inventory count
--   Query: rera_projects WHERE micro_market_id=? AND is_active=true
--   Index: idx_rera_projects_active_inv ON rera_projects(micro_market_id, is_active) WHERE is_active=true
--   Rationale: Partial index — only active rows indexed. ~60% space savings vs full index.
--   Note: idx_rera_projects_active_inv deliberately omits status because is_active=true
--     already filters to the working set; adding project_status would inflate index
--     without improving the COUNT(*) query plan.
--
-- Path 3: months_of_supply
--   Query: kaveri_registrations WHERE micro_market_id=? ORDER BY transaction_date DESC
--   Index: idx_kaveri_reg_market_date ON kaveri_registrations(micro_market_id, transaction_date DESC)
--   Rationale: Composite covers market filter + date sort in one index scan.
--
-- Path 4: IGR 90-day PSF median
--   Query: igr_transactions WHERE micro_market_id=? AND registration_date >= NOW()-INTERVAL '90 days'
--   Index: idx_igr_market_date_v2 ON igr_transactions(micro_market_id, registration_date DESC)
--   Rationale: Existing idx_igr_market_date uses market VARCHAR not micro_market_id UUID.
--     v2 index uses FK column for join consistency.
--
-- Path 5: v_opportunity_queue ranking
--   Query: opportunity_scores WHERE micro_market_id=? ORDER BY score DESC LIMIT N
--   Index: idx_opp_scores_market_score ON opportunity_scores(micro_market_id, score DESC)
--   Rationale: Covers WHERE + ORDER BY + LIMIT in one index-only scan.
--
-- Path 6: agent_registry spec JSONB search
--   Query: agent_registry WHERE spec @> '{"key":"val"}'
--   Index: idx_agent_registry_spec_gin ON agent_registry USING GIN(spec)
--   Rationale: GIN index on JSONB column enables @>, ?, ?| containment/index lookups.
-- ============================================================

-- Extensions (idempotent)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- EXISTING v1 TABLES (carried forward, IF NOT EXISTS)
-- ============================================================

CREATE TABLE IF NOT EXISTS micro_markets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    city VARCHAR(50) NOT NULL DEFAULT 'Bengaluru',
    state VARCHAR(50) NOT NULL DEFAULT 'Karnataka',
    geom GEOMETRY(POLYGON, 4326),
    centroid GEOMETRY(POINT, 4326),
    priority INTEGER DEFAULT 0,
    last_scraped_at TIMESTAMPTZ,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS developers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    name_normalized VARCHAR(200) UNIQUE,
    rera_promoter_id VARCHAR(100),
    grade CHAR(1),
    total_projects INTEGER DEFAULT 0,
    completed_projects INTEGER DEFAULT 0,
    delayed_projects INTEGER DEFAULT 0,
    avg_delay_months DECIMAL(5,2),
    total_units_launched INTEGER DEFAULT 0,
    total_units_sold INTEGER DEFAULT 0,
    absorption_rate_pct DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rera_projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rera_number VARCHAR(100) UNIQUE NOT NULL,
    project_name VARCHAR(300) NOT NULL,
    developer_id UUID REFERENCES developers(id),
    micro_market_id UUID REFERENCES micro_markets(id),
    address TEXT,
    district VARCHAR(100),
    taluk VARCHAR(100),
    locality VARCHAR(200),
    pincode VARCHAR(10),
    geom GEOMETRY(POINT, 4326),
    project_type VARCHAR(50),
    project_category VARCHAR(50),
    total_units INTEGER,
    sold_units INTEGER,
    unsold_units INTEGER,
    blocked_units INTEGER DEFAULT 0,
    total_land_area_sqm DECIMAL(12,2),
    total_built_up_area_sqm DECIMAL(12,2),
    price_min_psf DECIMAL(10,2),
    price_max_psf DECIMAL(10,2),
    price_avg_psf DECIMAL(10,2),
    unit_mix JSONB,
    amenities JSONB,
    launch_date DATE,
    registration_date DATE,
    possession_date DATE,
    plan_approval_date DATE,
    rera_expiry_date DATE,
    actual_completion_date DATE,
    delay_months INTEGER DEFAULT 0,
    completion_pct DECIMAL(5,2),
    project_status VARCHAR(512),
    rera_status VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    estimated_project_cost DECIMAL(15,2),
    amount_collected DECIMAL(15,2),
    architect_name VARCHAR(200),
    ca_name VARCHAR(200),
    structural_engineer VARCHAR(200),
    raw_data JSONB,
    detail_url TEXT,
    source_url TEXT,
    last_scraped_at TIMESTAMP,
    data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS project_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rera_project_id UUID REFERENCES rera_projects(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    sold_units INTEGER,
    unsold_units INTEGER,
    price_min_psf DECIMAL(10,2),
    price_max_psf DECIMAL(10,2),
    units_sold_this_period INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(rera_project_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS listings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source VARCHAR(50) NOT NULL,
    source_listing_id VARCHAR(200),
    source_url TEXT,
    micro_market_id UUID REFERENCES micro_markets(id),
    rera_project_id UUID REFERENCES rera_projects(id),
    property_type VARCHAR(50),
    transaction_type VARCHAR(20),
    bhk_config VARCHAR(30),
    carpet_area_sqft DECIMAL(10,2),
    built_up_area_sqft DECIMAL(10,2),
    super_built_up_sqft DECIMAL(10,2),
    plot_area_sqft DECIMAL(10,2),
    listed_price DECIMAL(15,2),
    price_psf DECIMAL(10,2),
    monthly_rent DECIMAL(10,2),
    security_deposit DECIMAL(10,2),
    deposit_months DECIMAL(4,1),
    address TEXT,
    locality VARCHAR(200),
    geom GEOMETRY(POINT, 4326),
    listed_at DATE,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    days_on_market INTEGER,
    is_new_launch BOOLEAN DEFAULT FALSE,
    is_rera_registered BOOLEAN,
    raw_rera_number VARCHAR(100),
    raw_data JSONB,
    data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source, source_listing_id)
);

CREATE TABLE IF NOT EXISTS kaveri_registrations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    registration_number VARCHAR(200),
    document_number VARCHAR(200),
    micro_market_id UUID REFERENCES micro_markets(id),
    rera_project_id UUID REFERENCES rera_projects(id),
    property_type VARCHAR(50),
    property_description TEXT,
    area_sqft DECIMAL(10,2),
    area_sqm DECIMAL(10,2),
    transaction_amount DECIMAL(15,2),
    guidance_value DECIMAL(15,2),
    stamp_duty_paid DECIMAL(12,2),
    registration_fee DECIMAL(10,2),
    buyer_name VARCHAR(200),
    seller_name VARCHAR(200),
    survey_number VARCHAR(100),
    village VARCHAR(100),
    hobli VARCHAR(100),
    taluk VARCHAR(100),
    district VARCHAR(100),
    geom GEOMETRY(POINT, 4326),
    transaction_date DATE,
    registration_date DATE,
    raw_data JSONB,
    data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS igr_transactions (
    id VARCHAR(32) PRIMARY KEY,
    micro_market_id UUID REFERENCES micro_markets(id),
    market VARCHAR(100) NOT NULL,
    survey_no VARCHAR(100),
    seller_name TEXT,
    buyer_name TEXT,
    consideration_amount BIGINT,
    area_sqft NUMERIC(12,2),
    registration_date DATE,
    sro_office VARCHAR(200),
    source VARCHAR(50) NOT NULL DEFAULT 'fallback',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS guidance_values (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    micro_market_id UUID REFERENCES micro_markets(id),
    locality VARCHAR(200),
    area_code VARCHAR(50),
    property_type VARCHAR(50),
    road_type VARCHAR(50),
    guidance_value_psf DECIMAL(10,2),
    guidance_value_per_sqm DECIMAL(10,2),
    effective_from DATE,
    effective_to DATE,
    source_document TEXT,
    data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS regulatory_zones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    authority VARCHAR(50) NOT NULL,
    zone_type VARCHAR(50) NOT NULL,
    zone_code VARCHAR(20),
    zone_description VARCHAR(200),
    far_base DECIMAL(5,2),
    far_road_9m DECIMAL(5,2),
    far_road_12m DECIMAL(5,2),
    far_road_18m DECIMAL(5,2),
    far_road_24m DECIMAL(5,2),
    far_road_30m_plus DECIMAL(5,2),
    front_setback_m DECIMAL(5,2),
    side_setback_m DECIMAL(5,2),
    rear_setback_m DECIMAL(5,2),
    max_height_m DECIMAL(5,2),
    ground_coverage_pct DECIMAL(5,2),
    mixed_use_permitted BOOLEAN DEFAULT FALSE,
    commercial_pct_permitted DECIMAL(5,2),
    parking_norm_per_unit VARCHAR(100),
    geom GEOMETRY(MULTIPOLYGON, 4326),
    dc_rules_reference VARCHAR(200),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS overlay_constraints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    constraint_type VARCHAR(100) NOT NULL,
    authority VARCHAR(100),
    buffer_distance_m DECIMAL(10,2),
    description TEXT,
    geom GEOMETRY(GEOMETRY, 4326),
    source_document TEXT,
    notified_date DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS infrastructure_pipeline (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(300) NOT NULL,
    infra_type VARCHAR(50) NOT NULL,
    authority VARCHAR(100),
    project_status VARCHAR(50),
    geom GEOMETRY(GEOMETRY, 4326),
    announced_date DATE,
    tender_date DATE,
    construction_start DATE,
    expected_completion DATE,
    actual_completion DATE,
    impact_radius_km DECIMAL(5,2) DEFAULT 1.0,
    description TEXT,
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS osm_edges (
    id BIGSERIAL PRIMARY KEY,
    market VARCHAR(100) NOT NULL,
    u BIGINT NOT NULL,
    v BIGINT NOT NULL,
    key INT,
    osmid BIGINT,
    length FLOAT,
    name TEXT,
    highway TEXT,
    geom GEOMETRY(LineString, 4326)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    micro_market_id UUID REFERENCES micro_markets(id),
    snapshot_date DATE NOT NULL,
    period VARCHAR(20) DEFAULT 'monthly',
    avg_psf_sale DECIMAL(10,2),
    median_psf_sale DECIMAL(10,2),
    min_psf_sale DECIMAL(10,2),
    max_psf_sale DECIMAL(10,2),
    avg_psf_rent DECIMAL(10,2),
    avg_rent_2bhk DECIMAL(10,2),
    avg_rent_3bhk DECIMAL(10,2),
    total_rera_projects INTEGER,
    active_rera_projects INTEGER,
    total_rera_units INTEGER,
    sold_rera_units INTEGER,
    unsold_rera_units INTEGER,
    avg_absorption_pct DECIMAL(5,2),
    total_active_listings INTEGER,
    new_listings_this_period INTEGER,
    listings_2bhk INTEGER,
    listings_3bhk INTEGER,
    registrations_this_period INTEGER,
    avg_transaction_psf DECIMAL(10,2),
    avg_guidance_value_psf DECIMAL(10,2),
    avg_guidance_market_gap_pct DECIMAL(5,2),
    active_developers INTEGER,
    grade_a_developers INTEGER,
    grade_b_developers INTEGER,
    new_launches_this_period INTEGER,
    market_summary TEXT,
    key_signals JSONB,
    risk_flags JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(micro_market_id, snapshot_date, period)
);

CREATE TABLE IF NOT EXISTS news_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cid VARCHAR(100) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    source VARCHAR(100),
    source_url TEXT,
    published_at DATE,
    summary TEXT,
    signal_type VARCHAR(50),
    key_insight TEXT,
    micro_market_id UUID REFERENCES micro_markets(id),
    raw_data JSONB,
    sentiment_score DOUBLE PRECISION,
    sentiment_label VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_name VARCHAR(100) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    micro_market VARCHAR(100),
    status VARCHAR(50) DEFAULT 'started',
    records_scraped INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    duration_seconds INTEGER
);

CREATE TABLE IF NOT EXISTS agent_memories (
    memory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    market TEXT,
    fact TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.6 CHECK (confidence BETWEEN 0.0 AND 1.0),
    source_count INT DEFAULT 1,
    last_confirmed DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS board_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market TEXT NOT NULL,
    initiated_by TEXT NOT NULL DEFAULT 'ceo',
    pitch_text TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    bd_response TEXT,
    finance_response TEXT,
    engineering_response TEXT,
    ops_response TEXT,
    legal_response TEXT,
    ceo_synthesis TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    owner VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    priority VARCHAR(10) NOT NULL DEFAULT 'medium',
    source_type VARCHAR(30),
    source_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel VARCHAR(50) NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    color INT DEFAULT 3447003,
    status VARCHAR(20) NOT NULL DEFAULT 'sent',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_registry (
    id VARCHAR(100) PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    department VARCHAR(50),
    spec JSONB NOT NULL,
    llm_tier VARCHAR(20) NOT NULL DEFAULT 'analysis',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    hired_on TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- v2 NEW TABLES (15)
-- ============================================================

-- surveys: Land parcels as first-class entities
CREATE TABLE IF NOT EXISTS surveys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    survey_no VARCHAR(100) NOT NULL,
    micro_market_id UUID NOT NULL REFERENCES micro_markets(id),
    village VARCHAR(200),
    hobli VARCHAR(200),
    taluk VARCHAR(200),
    district VARCHAR(100),
    total_area_acres DECIMAL(12,4),
    total_area_sqft DECIMAL(14,2),
    geom GEOMETRY(POLYGON, 4326),
    land_type VARCHAR(50),
    ownership_type VARCHAR(50),
    dc_conversion_status VARCHAR(50),
    dc_order_no VARCHAR(100),
    dc_order_date DATE,
    khata_no VARCHAR(100),
    khata_type VARCHAR(50),
    rtc_count INTEGER DEFAULT 0,
    litigation_count INTEGER DEFAULT 0,
    encumbrance_clear BOOLEAN DEFAULT FALSE,
    is_aggregated BOOLEAN DEFAULT FALSE,
    parent_survey_id UUID REFERENCES surveys(id) ON DELETE SET NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(survey_no, micro_market_id)
);

-- rtc_records: Bhoomi RTC extracts (Records of Rights, Tenancy and Crops)
CREATE TABLE IF NOT EXISTS rtc_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    survey_id UUID REFERENCES surveys(id) ON DELETE CASCADE,
    survey_no VARCHAR(100) NOT NULL,
    micro_market_id UUID REFERENCES micro_markets(id),
    owner_name TEXT,
    owner_share DECIMAL(5,2),
    cultivation_status VARCHAR(100),
    crop_grown VARCHAR(100),
    irrigation_type VARCHAR(100),
    land_type VARCHAR(100),
    extent_acres DECIMAL(10,4),
    mutation_no VARCHAR(100),
    mutation_date DATE,
    rtc_period VARCHAR(20),
    rtc_year INTEGER,
    source VARCHAR(50) DEFAULT 'bhoomi_portal',
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(survey_no, rtc_period, rtc_year)
);

-- khata_records: BBMP Khata status (property tax assessment records)
CREATE TABLE IF NOT EXISTS khata_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    khata_no VARCHAR(100) NOT NULL,
    khata_type VARCHAR(50) NOT NULL,
    survey_no VARCHAR(100),
    survey_id UUID REFERENCES surveys(id) ON DELETE CASCADE,
    micro_market_id UUID REFERENCES micro_markets(id),
    property_address TEXT,
    owner_name TEXT,
    property_usage VARCHAR(100),
    zone VARCHAR(50),
    ward VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    source VARCHAR(50) DEFAULT 'bbmp_portal',
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(khata_no)
);

-- litigations: Legal litigation records across courts
CREATE TABLE IF NOT EXISTS litigations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_no VARCHAR(200) NOT NULL,
    court_name VARCHAR(200),
    survey_no VARCHAR(100),
    survey_id UUID REFERENCES surveys(id),
    micro_market_id UUID REFERENCES micro_markets(id),
    case_type VARCHAR(100),
    plaintiff_name TEXT,
    defendant_name TEXT,
    filing_date DATE,
    last_hearing_date DATE,
    next_hearing_date DATE,
    case_status VARCHAR(100),
    case_stage VARCHAR(100),
    description TEXT,
    relief_sought TEXT,
    is_encumbrance BOOLEAN DEFAULT FALSE,
    source VARCHAR(50) DEFAULT 'indiankanoon',
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- distressed_opps: Distressed developer opportunities
CREATE TABLE IF NOT EXISTS distressed_opps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    developer_id UUID REFERENCES developers(id),
    developer_name VARCHAR(200) NOT NULL,
    micro_market_id UUID REFERENCES micro_markets(id),
    project_id UUID REFERENCES rera_projects(id),
    distress_score DECIMAL(8,4),
    delay_months INTEGER,
    incomplete_ratio DECIMAL(5,2),
    complaint_proxy DECIMAL(5,2),
    alert_level VARCHAR(20) DEFAULT 'watch',
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    is_actioned BOOLEAN DEFAULT FALSE,
    actioned_at TIMESTAMPTZ,
    notes TEXT
);

-- developer_health: Rolling developer health scores
CREATE TABLE IF NOT EXISTS developer_health (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    developer_id UUID UNIQUE NOT NULL REFERENCES developers(id),
    developer_name VARCHAR(200) NOT NULL,
    health_score DECIMAL(5,2),
    financial_stability DECIMAL(5,2),
    project_completion_rate DECIMAL(5,2),
    avg_delay_months DECIMAL(5,2),
    legal_compliance_score DECIMAL(5,2),
    market_reputation VARCHAR(50),
    distress_signals JSONB,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- demand_signals: Market demand signals per period
CREATE TABLE IF NOT EXISTS demand_signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    micro_market_id UUID NOT NULL REFERENCES micro_markets(id),
    signal_date DATE NOT NULL,
    median_days_on_market INTEGER,
    slow_market_flag BOOLEAN DEFAULT FALSE,
    fastest_config VARCHAR(30),
    dominant_ticket_size VARCHAR(30),
    nri_transaction_pct DECIMAL(5,2),
    price_revision_rate DECIMAL(5,2),
    absorption_rates JSONB,
    source VARCHAR(50) DEFAULT 'computed',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(micro_market_id, signal_date)
);

-- deals: Deal pipeline CRM
CREATE TABLE IF NOT EXISTS deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_name VARCHAR(200) NOT NULL,
    survey_no VARCHAR(100),
    survey_id UUID REFERENCES surveys(id),
    micro_market_id UUID REFERENCES micro_markets(id),
    developer_id UUID REFERENCES developers(id),
    deal_type VARCHAR(50) NOT NULL,
    stage VARCHAR(50) NOT NULL DEFAULT 'identified',
    area_acres DECIMAL(10,4),
    ask_psf DECIMAL(12,2),
    guidance_value_psf DECIMAL(12,2),
    negotiated_price DECIMAL(15,2),
    landowner_ratio DECIMAL(5,2),
    lls_equity_share DECIMAL(5,2),
    irr_base DECIMAL(5,2),
    irr_bull DECIMAL(5,2),
    irr_bear DECIMAL(5,2),
    verdict VARCHAR(20),
    deal_lead VARCHAR(100),
    contacted_at TIMESTAMPTZ,
    expected_close TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    notes TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- deal_memos: Structured deal memos
CREATE TABLE IF NOT EXISTS deal_memos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id),
    title VARCHAR(200) NOT NULL,
    memo_type VARCHAR(50) DEFAULT 'full',
    sections JSONB NOT NULL,
    recommendation VARCHAR(20),
    recommendation_text TEXT,
    created_by VARCHAR(100),
    session_id UUID REFERENCES board_sessions(session_id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- lls_projects: LLS internal project milestones tracker
CREATE TABLE IF NOT EXISTS lls_projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID REFERENCES deals(id),
    project_name VARCHAR(200) NOT NULL,
    survey_no VARCHAR(100),
    micro_market_id UUID REFERENCES micro_markets(id),
    milestones JSONB,
    project_status VARCHAR(50) DEFAULT 'planning',
    lls_investment_rs DECIMAL(15,2),
    lls_equity_pct DECIMAL(5,2),
    partner_name VARCHAR(200),
    target_irr DECIMAL(5,2),
    actual_irr DECIMAL(5,2),
    start_date DATE,
    expected_completion DATE,
    actual_completion DATE,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- agreements: Legal agreements repository
CREATE TABLE IF NOT EXISTS agreements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID REFERENCES deals(id),
    agreement_type VARCHAR(50) NOT NULL,
    title VARCHAR(200),
    parties JSONB NOT NULL,
    key_terms JSONB,
    signed_date DATE,
    effective_date DATE,
    expiry_date DATE,
    document_url TEXT,
    status VARCHAR(50) DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- compliance_log: Compliance tracking for all entities
CREATE TABLE IF NOT EXISTS compliance_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    compliance_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    due_date DATE,
    completed_date DATE,
    authority VARCHAR(100),
    reference_no VARCHAR(200),
    notes TEXT,
    assigned_to VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- opportunity_scores: Scored opportunities for deal prospecting
CREATE TABLE IF NOT EXISTS opportunity_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    survey_id UUID REFERENCES surveys(id) ON DELETE CASCADE,
    survey_no VARCHAR(100),
    micro_market_id UUID NOT NULL REFERENCES micro_markets(id),
    developer_id UUID REFERENCES developers(id) ON DELETE SET NULL,
    score DECIMAL(5,4) NOT NULL CHECK (score >= 0 AND score <= 1),
    irr_score DECIMAL(5,4) CHECK (irr_score >= 0 AND irr_score <= 1),
    legal_score DECIMAL(5,4) CHECK (legal_score >= 0 AND legal_score <= 1),
    timing_score DECIMAL(5,4) CHECK (timing_score >= 0 AND timing_score <= 1),
    distress_score DECIMAL(5,4) CHECK (distress_score >= 0 AND distress_score <= 1),
    exclusivity_score DECIMAL(5,4) CHECK (exclusivity_score >= 0 AND exclusivity_score <= 1),
    components JSONB,
    best_deal_type VARCHAR(50),
    estimated_jd_irr DECIMAL(5,2),
    legal_risk_level VARCHAR(20),
    next_action TEXT,
    expiry_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    pruned_at TIMESTAMPTZ
);

-- ingest_log: Data ingest audit trail
CREATE TABLE IF NOT EXISTS ingest_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plugin_id VARCHAR(100) NOT NULL,
    source_id VARCHAR(100),
    market VARCHAR(100),
    entity_type VARCHAR(50),
    entity_id VARCHAR(200),
    data JSONB,
    raw_hash VARCHAR(64),
    confidence DECIMAL(3,2) DEFAULT 1.0,
    validation_errors JSONB,
    status VARCHAR(20) DEFAULT 'success',
    error_message TEXT,
    scraped_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- v2 INDEXES
-- ============================================================

-- Existing v1 indexes (recreated idempotently)
CREATE INDEX IF NOT EXISTS idx_rera_projects_market ON rera_projects(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_rera_projects_developer ON rera_projects(developer_id);
CREATE INDEX IF NOT EXISTS idx_rera_projects_status ON rera_projects(project_status);
CREATE INDEX IF NOT EXISTS idx_rera_projects_number ON rera_projects(rera_number);
CREATE INDEX IF NOT EXISTS idx_listings_market ON listings(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_listings_type ON listings(transaction_type, property_type);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_kaveri_date ON kaveri_registrations(transaction_date);
CREATE INDEX IF NOT EXISTS idx_kaveri_market ON kaveri_registrations(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_market_snapshots ON market_snapshots(micro_market_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status, started_at);
CREATE INDEX IF NOT EXISTS idx_news_articles_market ON news_articles(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_news_articles_signal ON news_articles(signal_type);
CREATE INDEX IF NOT EXISTS idx_news_articles_date ON news_articles(published_at);
CREATE INDEX IF NOT EXISTS idx_board_sessions_market ON board_sessions(market, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_board_sessions_status ON board_sessions(status);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner);
CREATE INDEX IF NOT EXISTS idx_alerts_channel ON alerts(channel);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_registry_dept ON agent_registry(department);
CREATE INDEX IF NOT EXISTS idx_agent_registry_active ON agent_registry(active);
CREATE INDEX IF NOT EXISTS idx_agent_registry_hired_on ON agent_registry(hired_on DESC);

-- PostGIS spatial indexes
CREATE INDEX IF NOT EXISTS idx_rera_projects_geom ON rera_projects USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_listings_geom ON listings USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_kaveri_geom ON kaveri_registrations USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_regulatory_zones_geom ON regulatory_zones USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_overlay_constraints_geom ON overlay_constraints USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_infrastructure_geom ON infrastructure_pipeline USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_osm_edges_market ON osm_edges(market);
CREATE INDEX IF NOT EXISTS idx_osm_edges_geom ON osm_edges USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_edges_u ON osm_edges (u);
CREATE INDEX IF NOT EXISTS idx_osm_edges_v ON osm_edges (v);
CREATE INDEX IF NOT EXISTS idx_osm_edges_uv ON osm_edges (u, v);

-- Fuzzy search indexes
CREATE INDEX IF NOT EXISTS idx_rera_projects_name_trgm ON rera_projects USING GIN(project_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_developers_name_trgm ON developers USING GIN(name gin_trgm_ops);

-- Kaveri registrations partial unique index
CREATE UNIQUE INDEX IF NOT EXISTS idx_kaveri_reg_unique
    ON kaveri_registrations(registration_number)
    WHERE registration_number IS NOT NULL AND registration_number != '';

-- T-709 Path 1: Distressed developer scan
CREATE INDEX IF NOT EXISTS idx_rera_projects_distressed
    ON rera_projects(micro_market_id, project_status, possession_date);

-- T-709 Path 2: Active inventory count (partial index)
CREATE INDEX IF NOT EXISTS idx_rera_projects_active_inv
    ON rera_projects(micro_market_id, is_active)
    WHERE is_active = TRUE;

-- T-709 Path 3: Kaveri registrations for months_of_supply
CREATE INDEX IF NOT EXISTS idx_kaveri_reg_market_date
    ON kaveri_registrations(micro_market_id, transaction_date DESC);

-- T-709 Path 4: IGR 90-day PSF median (v2: uses micro_market_id FK not market VARCHAR)
CREATE INDEX IF NOT EXISTS idx_igr_market_date_v2
    ON igr_transactions(micro_market_id, registration_date DESC);

-- T-709 Path 6: Agent registry JSONB GIN search
CREATE INDEX IF NOT EXISTS idx_agent_registry_spec_gin
    ON agent_registry USING GIN(spec);

-- v2 new table indexes

-- surveys
CREATE INDEX IF NOT EXISTS idx_surveys_market ON surveys(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_surveys_survey_no ON surveys(survey_no);
CREATE INDEX IF NOT EXISTS idx_surveys_geom ON surveys USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_surveys_parent ON surveys(parent_survey_id);

-- rtc_records
CREATE INDEX IF NOT EXISTS idx_rtc_survey ON rtc_records(survey_id);
CREATE INDEX IF NOT EXISTS idx_rtc_survey_no ON rtc_records(survey_no);
CREATE INDEX IF NOT EXISTS idx_rtc_market ON rtc_records(micro_market_id);

-- khata_records
CREATE INDEX IF NOT EXISTS idx_khata_survey ON khata_records(survey_id);
CREATE INDEX IF NOT EXISTS idx_khata_market ON khata_records(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_khata_type ON khata_records(khata_type);

-- litigations
CREATE INDEX IF NOT EXISTS idx_litigations_survey ON litigations(survey_id);
CREATE INDEX IF NOT EXISTS idx_litigations_survey_no ON litigations(survey_no);
CREATE INDEX IF NOT EXISTS idx_litigations_market ON litigations(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_litigations_status ON litigations(case_status);

-- distressed_opps
CREATE INDEX IF NOT EXISTS idx_distressed_dev ON distressed_opps(developer_id);
CREATE INDEX IF NOT EXISTS idx_distressed_score ON distressed_opps(distress_score DESC);
CREATE INDEX IF NOT EXISTS idx_distressed_market ON distressed_opps(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_distressed_alert ON distressed_opps(alert_level);

-- developer_health
CREATE INDEX IF NOT EXISTS idx_dev_health_score ON developer_health(health_score DESC);

-- demand_signals
CREATE INDEX IF NOT EXISTS idx_demand_market ON demand_signals(micro_market_id, signal_date DESC);

-- deals
CREATE INDEX IF NOT EXISTS idx_deals_market ON deals(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
CREATE INDEX IF NOT EXISTS idx_deals_survey ON deals(survey_id);
CREATE INDEX IF NOT EXISTS idx_deals_verdict ON deals(verdict);

-- deal_memos
CREATE INDEX IF NOT EXISTS idx_memos_deal ON deal_memos(deal_id);
CREATE INDEX IF NOT EXISTS idx_memos_type ON deal_memos(memo_type);

-- lls_projects
CREATE INDEX IF NOT EXISTS idx_lls_market ON lls_projects(micro_market_id);
CREATE INDEX IF NOT EXISTS idx_lls_deal ON lls_projects(deal_id);
CREATE INDEX IF NOT EXISTS idx_lls_status ON lls_projects(project_status);

-- agreements
CREATE INDEX IF NOT EXISTS idx_agreements_deal ON agreements(deal_id);
CREATE INDEX IF NOT EXISTS idx_agreements_type ON agreements(agreement_type);
CREATE INDEX IF NOT EXISTS idx_agreements_status ON agreements(status);

-- compliance_log
CREATE INDEX IF NOT EXISTS idx_compliance_entity ON compliance_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_compliance_status ON compliance_log(status);
CREATE INDEX IF NOT EXISTS idx_compliance_due ON compliance_log(due_date);

-- opportunity_scores
-- T-709 Path 5: v_opportunity_queue ranking
CREATE INDEX IF NOT EXISTS idx_opp_scores_market_score ON opportunity_scores(micro_market_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_opp_scores_survey ON opportunity_scores(survey_id);
CREATE INDEX IF NOT EXISTS idx_opp_scores_active ON opportunity_scores(is_active);
CREATE INDEX IF NOT EXISTS idx_opp_scores_expiry ON opportunity_scores(expiry_date);

-- ingest_log
CREATE INDEX IF NOT EXISTS idx_ingest_plugin ON ingest_log(plugin_id);
CREATE INDEX IF NOT EXISTS idx_ingest_market ON ingest_log(market);
CREATE INDEX IF NOT EXISTS idx_ingest_entity ON ingest_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_ingest_status ON ingest_log(status);
CREATE INDEX IF NOT EXISTS idx_ingest_created ON ingest_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_hash ON ingest_log(raw_hash);

-- ============================================================
-- v2 AUTO-UPDATE TRIGGER for updated_at columns
-- Applies to all v2 tables with updated_at column
-- ============================================================
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT unnest(ARRAY[
            'surveys', 'rtc_records', 'litigations', 'distressed_opps',
            'developer_health', 'deals', 'deal_memos', 'lls_projects',
            'agreements', 'compliance_log'
        ])
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_%s_updated_at ON %s; CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON %s FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();',
            tbl, tbl, tbl, tbl
        );
    END LOOP;
END;
$$;

-- ============================================================
-- v2 DELAY MONTHS TRIGGER (rera_projects)
-- ============================================================
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

DROP TRIGGER IF EXISTS trg_compute_delay_months ON rera_projects;
CREATE TRIGGER trg_compute_delay_months
BEFORE INSERT OR UPDATE OF actual_completion_date, possession_date
ON rera_projects
FOR EACH ROW EXECUTE FUNCTION fn_compute_delay_months();

-- ============================================================
-- v2 AGENT MEMORIES UNIQUE CONSTRAINT (idempotent)
-- ============================================================
ALTER TABLE agent_memories
  DROP CONSTRAINT IF EXISTS agent_memories_unique_fact;
ALTER TABLE agent_memories
  ADD CONSTRAINT agent_memories_unique_fact UNIQUE (agent_id, market, fact);

-- ============================================================
-- ALEMBIC VERSION STAMP — only stamp if no prior migrations exist
-- ============================================================
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

INSERT INTO alembic_version (version_num)
SELECT '0100_v2_schema'
WHERE NOT EXISTS (SELECT 1 FROM alembic_version);
