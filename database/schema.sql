-- ============================================================
-- RE_OS — Real Estate Intelligence OS
-- PostgreSQL + PostGIS Schema
-- Seed: Karnataka / Bengaluru
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm; -- for fuzzy text search

-- ============================================================
-- MICRO MARKETS
-- The geographic anchor for everything
-- ============================================================
CREATE TABLE micro_markets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,           -- yelahanka, devanahalli, etc.
    city VARCHAR(50) NOT NULL DEFAULT 'Bengaluru',
    state VARCHAR(50) NOT NULL DEFAULT 'Karnataka',
    geom GEOMETRY(POLYGON, 4326),                -- boundary polygon (optional, add later)
    centroid GEOMETRY(POINT, 4326),              -- center point
    priority INTEGER DEFAULT 0,                  -- 1 = active, 0 = queued
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- DEVELOPERS
-- Every promoter registered on RERA Karnataka
-- ============================================================
CREATE TABLE developers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    name_normalized VARCHAR(200) UNIQUE,         -- lowercase, trimmed for dedup
    rera_promoter_id VARCHAR(100),
    grade CHAR(1),                               -- A = Tier 1, B = Tier 2, C = small/unknown
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

-- ============================================================
-- RERA PROJECTS
-- The primary intelligence layer — all RERA-registered projects
-- ============================================================
CREATE TABLE rera_projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rera_number VARCHAR(100) UNIQUE NOT NULL,    -- PRM/KA/RERA/...
    project_name VARCHAR(300) NOT NULL,
    developer_id UUID REFERENCES developers(id),
    micro_market_id UUID REFERENCES micro_markets(id),

    -- Location
    address TEXT,
    district VARCHAR(100),
    taluk VARCHAR(100),
    locality VARCHAR(200),
    pincode VARCHAR(10),
    geom GEOMETRY(POINT, 4326),                  -- geocoded later

    -- Project classification
    project_type VARCHAR(50),                    -- Apartment, Villa, Plotted, Mixed, Commercial
    project_category VARCHAR(50),                -- Residential, Commercial, Mixed Use

    -- Unit inventory
    total_units INTEGER,
    sold_units INTEGER,
    unsold_units INTEGER,
    blocked_units INTEGER DEFAULT 0,
    absorption_pct DECIMAL(5,2)
        GENERATED ALWAYS AS (
            CASE WHEN total_units > 0
                 THEN ROUND((sold_units::DECIMAL / total_units) * 100, 2)
                 ELSE 0 END
        ) STORED,

    -- Area details
    total_land_area_sqm DECIMAL(12,2),
    total_built_up_area_sqm DECIMAL(12,2),

    -- Pricing (psf in INR)
    price_min_psf DECIMAL(10,2),
    price_max_psf DECIMAL(10,2),
    price_avg_psf DECIMAL(10,2),

    -- BHK mix (JSONB for flexibility)
    -- Example: {"2BHK": {"count": 100, "area_min": 950, "area_max": 1100}}
    unit_mix JSONB,

    -- Amenities & features
    amenities JSONB,

    -- Timeline
    launch_date DATE,
    registration_date DATE,
    possession_date DATE,
    plan_approval_date DATE,                     -- BDA/BBMP plan sanction date (from RERA detail page)
    rera_expiry_date DATE,
    actual_completion_date DATE,
    delay_months INTEGER DEFAULT 0,
    completion_pct DECIMAL(5,2),                 -- Construction completion % (from RERA detail page)

    -- Status
    project_status VARCHAR(512),                 -- RERA status strings can be long (253+ chars seen)
    rera_status VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,

    -- Financial (from RERA disclosures)
    estimated_project_cost DECIMAL(15,2),
    amount_collected DECIMAL(15,2),

    -- RERA disclosure details
    architect_name VARCHAR(200),
    ca_name VARCHAR(200),                        -- Chartered Accountant for RERA compliance
    structural_engineer VARCHAR(200),

    -- Raw data preservation
    raw_data JSONB,
    -- RERA detail page URL for deep-dive enrichment
    detail_url TEXT,                                -- /projectDetails?action=...
    source_url TEXT,                                -- RERA listing page URL
    last_scraped_at TIMESTAMP,
    data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated'
        CHECK (data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- delay_months: computed by trigger rather than GENERATED ALWAYS AS to avoid
-- PostgreSQL portability issues on DB reinit with PostGIS image variants.
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

CREATE TRIGGER trg_compute_delay_months
BEFORE INSERT OR UPDATE OF actual_completion_date, possession_date
ON rera_projects
FOR EACH ROW EXECUTE FUNCTION fn_compute_delay_months();

-- ============================================================
-- PROJECT QUARTERLY SNAPSHOTS
-- Track absorption velocity over time
-- ============================================================
CREATE TABLE project_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rera_project_id UUID REFERENCES rera_projects(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    sold_units INTEGER,
    unsold_units INTEGER,
    price_min_psf DECIMAL(10,2),
    price_max_psf DECIMAL(10,2),
    units_sold_this_period INTEGER,              -- delta from last snapshot
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(rera_project_id, snapshot_date)
);

-- ============================================================
-- LISTINGS
-- Live market listings from portals (99acres, MagicBricks, NoBroker)
-- ============================================================
CREATE TABLE listings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source VARCHAR(50) NOT NULL,                 -- 99acres, magicbricks, nobroker, housing
    source_listing_id VARCHAR(200),
    source_url TEXT,
    micro_market_id UUID REFERENCES micro_markets(id),
    rera_project_id UUID REFERENCES rera_projects(id),

    -- Property
    property_type VARCHAR(50),                   -- Apartment, Villa, Plot, Commercial
    transaction_type VARCHAR(20),                -- Sale, Rent
    bhk_config VARCHAR(30),                      -- 2 BHK, 3 BHK, Studio, etc.

    -- Area
    carpet_area_sqft DECIMAL(10,2),
    built_up_area_sqft DECIMAL(10,2),
    super_built_up_sqft DECIMAL(10,2),
    plot_area_sqft DECIMAL(10,2),

    -- Pricing
    listed_price DECIMAL(15,2),
    price_psf DECIMAL(10,2),
    monthly_rent DECIMAL(10,2),
    security_deposit DECIMAL(10,2),
    deposit_months DECIMAL(4,1),

    -- Location
    address TEXT,
    locality VARCHAR(200),
    geom GEOMETRY(POINT, 4326),

    -- Listing lifecycle
    listed_at DATE,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    days_on_market INTEGER,

    -- Flags
    is_new_launch BOOLEAN DEFAULT FALSE,
    is_rera_registered BOOLEAN,
    raw_rera_number VARCHAR(100),

    raw_data JSONB,
    data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated'
        CHECK (data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(source, source_listing_id)
);

-- ============================================================
-- KAVERI REGISTRATIONS
-- Actual property registrations = real transaction prices
-- Source of truth for market values
-- ============================================================
CREATE TABLE kaveri_registrations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    registration_number VARCHAR(200),
    document_number VARCHAR(200),
    micro_market_id UUID REFERENCES micro_markets(id),
    rera_project_id UUID REFERENCES rera_projects(id),

    -- Property
    property_type VARCHAR(50),
    property_description TEXT,
    area_sqft DECIMAL(10,2),
    area_sqm DECIMAL(10,2),

    -- Transaction
    transaction_amount DECIMAL(15,2),            -- actual registered value
    guidance_value DECIMAL(15,2),               -- government circle rate
    guidance_market_gap_pct DECIMAL(5,2)
        GENERATED ALWAYS AS (
            CASE WHEN guidance_value > 0
                 THEN ROUND(((transaction_amount - guidance_value) / guidance_value) * 100, 2)
                 ELSE NULL END
        ) STORED,
    stamp_duty_paid DECIMAL(12,2),
    registration_fee DECIMAL(10,2),

    -- Parties
    buyer_name VARCHAR(200),
    seller_name VARCHAR(200),

    -- Location
    survey_number VARCHAR(100),
    village VARCHAR(100),
    hobli VARCHAR(100),
    taluk VARCHAR(100),
    district VARCHAR(100),
    geom GEOMETRY(POINT, 4326),

    -- Time
    transaction_date DATE,
    registration_date DATE,

    raw_data JSONB,
    data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated'
        CHECK (data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')),
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- GUIDANCE VALUES
-- Government circle rates by zone — updated annually
-- ============================================================
CREATE TABLE guidance_values (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    micro_market_id UUID REFERENCES micro_markets(id),
    locality VARCHAR(200),
    area_code VARCHAR(50),
    property_type VARCHAR(50),                   -- Residential, Commercial, Industrial
    road_type VARCHAR(50),                       -- Main Road, Cross Road, Layout
    guidance_value_psf DECIMAL(10,2),
    guidance_value_per_sqm DECIMAL(10,2),
    effective_from DATE,
    effective_to DATE,
    source_document TEXT,
    data_source VARCHAR(20) NOT NULL DEFAULT 'seed_estimated'
        CHECK (data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')),
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- REGULATORY ZONES
-- The bylaw intelligence layer
-- What can be built where, under which rules
-- ============================================================
CREATE TABLE regulatory_zones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    authority VARCHAR(50) NOT NULL,              -- BBMP, BDA, BMRDA, GP, KIADB
    zone_type VARCHAR(50) NOT NULL,              -- Land use zone from CDP
    zone_code VARCHAR(20),                       -- R1, R2, C1, C2, MU, GB, etc.
    zone_description VARCHAR(200),

    -- DC Rule parameters
    -- FAR changes with road width in Karnataka
    far_base DECIMAL(5,2),
    far_road_9m DECIMAL(5,2),
    far_road_12m DECIMAL(5,2),
    far_road_18m DECIMAL(5,2),
    far_road_24m DECIMAL(5,2),
    far_road_30m_plus DECIMAL(5,2),

    -- Setbacks (meters)
    front_setback_m DECIMAL(5,2),
    side_setback_m DECIMAL(5,2),
    rear_setback_m DECIMAL(5,2),

    -- Other development controls
    max_height_m DECIMAL(5,2),
    ground_coverage_pct DECIMAL(5,2),
    mixed_use_permitted BOOLEAN DEFAULT FALSE,
    commercial_pct_permitted DECIMAL(5,2),

    -- Parking norms
    parking_norm_per_unit VARCHAR(100),          -- "1 car per 2BHK, 2 cars per 3BHK"

    -- Geometry
    geom GEOMETRY(MULTIPOLYGON, 4326),
    dc_rules_reference VARCHAR(200),             -- e.g., "DC Rules 2015, Clause 7.3"
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- OVERLAY CONSTRAINTS
-- Things that restrict what you can do on a site
-- Regardless of zone — these trump everything
-- ============================================================
CREATE TABLE overlay_constraints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    constraint_type VARCHAR(100) NOT NULL,
    -- Types: lake_buffer, rajakaluv_buffer, ht_line_buffer,
    --        airport_funnel, heritage_zone, nh_setback, sh_setback,
    --        proposed_road_widening, forest_buffer
    authority VARCHAR(100),
    buffer_distance_m DECIMAL(10,2),
    description TEXT,
    geom GEOMETRY(GEOMETRY, 4326),               -- line, polygon, or buffer
    source_document TEXT,
    notified_date DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- INFRASTRUCTURE PIPELINE
-- Future value map — what's coming
-- ============================================================
CREATE TABLE infrastructure_pipeline (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(300) NOT NULL,
    infra_type VARCHAR(50) NOT NULL,             -- Metro, Road, Expressway, SWD, Power, Water
    authority VARCHAR(100),                      -- BMRCL, BBMP, NHAI, BDA, BWSSB, BESCOM
    project_status VARCHAR(50),                  -- Proposed, DPR_Approved, Tendered, Under_Construction, Completed
    geom GEOMETRY(GEOMETRY, 4326),               -- line for roads/metro, polygon for areas

    -- Timeline
    announced_date DATE,
    tender_date DATE,
    construction_start DATE,
    expected_completion DATE,
    actual_completion DATE,

    -- Impact radius for value analysis
    impact_radius_km DECIMAL(5,2) DEFAULT 1.0,

    -- Notes
    description TEXT,
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- MICRO MARKET SNAPSHOTS
-- Aggregated intelligence per market per period
-- This is what Jinu reads
-- ============================================================
CREATE TABLE market_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    micro_market_id UUID REFERENCES micro_markets(id),
    snapshot_date DATE NOT NULL,
    period VARCHAR(20) DEFAULT 'monthly',        -- daily, weekly, monthly, quarterly

    -- Pricing
    avg_psf_sale DECIMAL(10,2),
    median_psf_sale DECIMAL(10,2),
    min_psf_sale DECIMAL(10,2),
    max_psf_sale DECIMAL(10,2),
    avg_psf_rent DECIMAL(10,2),
    avg_rent_2bhk DECIMAL(10,2),
    avg_rent_3bhk DECIMAL(10,2),

    -- RERA inventory
    total_rera_projects INTEGER,
    active_rera_projects INTEGER,
    total_rera_units INTEGER,
    sold_rera_units INTEGER,
    unsold_rera_units INTEGER,
    avg_absorption_pct DECIMAL(5,2),

    -- Market listings
    total_active_listings INTEGER,
    new_listings_this_period INTEGER,
    listings_2bhk INTEGER,
    listings_3bhk INTEGER,

    -- Transactions (Kaveri)
    registrations_this_period INTEGER,
    avg_transaction_psf DECIMAL(10,2),
    avg_guidance_value_psf DECIMAL(10,2),
    avg_guidance_market_gap_pct DECIMAL(5,2),

    -- Developer activity
    active_developers INTEGER,
    grade_a_developers INTEGER,
    grade_b_developers INTEGER,
    new_launches_this_period INTEGER,

    -- AI-generated intelligence
    market_summary TEXT,                         -- Ollama/OpenRouter generated
    key_signals JSONB,                           -- Array of notable signals
    risk_flags JSONB,                            -- Array of risk items

    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(micro_market_id, snapshot_date, period)
);

-- ============================================================
-- NEWS ARTICLES
-- Market signals from news_scout (Google News RSS + ET Realty)
-- ============================================================
CREATE TABLE news_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cid VARCHAR(100) UNIQUE NOT NULL,              -- content ID from scout_memory
    title TEXT NOT NULL,
    source VARCHAR(100),
    source_url TEXT,
    published_at DATE,
    summary TEXT,
    signal_type VARCHAR(50),                       -- new_launch, price_change, regulatory, developer_news, infrastructure
    key_insight TEXT,
    micro_market_id UUID REFERENCES micro_markets(id),
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_news_articles_market ON news_articles(micro_market_id);
CREATE INDEX idx_news_articles_signal ON news_articles(signal_type);
CREATE INDEX idx_news_articles_date ON news_articles(published_at);

-- ============================================================
-- AGENT RUN LOGS
-- Track every agent job — what ran, what it found, errors
-- ============================================================
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_name VARCHAR(100) NOT NULL,
    task_type VARCHAR(100) NOT NULL,
    micro_market VARCHAR(100),
    status VARCHAR(50) DEFAULT 'started',        -- started, completed, failed, partial
    records_scraped INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    duration_seconds INTEGER                                -- populated by LogAgentRunTool on completion
);

-- ============================================================
-- AGENT MEMORIES
-- Persistent per-agent fact memory with confidence tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_memories (
    memory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    market TEXT,
    fact TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.6 CHECK (confidence BETWEEN 0.0 AND 1.0),
    source_count INT DEFAULT 1,
    last_confirmed DATE DEFAULT CURRENT_DATE,
    superseded_by UUID REFERENCES agent_memories(memory_id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_memories_agent ON agent_memories(agent_id, market);
CREATE INDEX IF NOT EXISTS idx_agent_memories_confidence ON agent_memories(confidence DESC);

-- ============================================================
-- SPATIAL INDEXES (PostGIS)
-- ============================================================
CREATE INDEX idx_rera_projects_geom ON rera_projects USING GIST(geom);
CREATE INDEX idx_listings_geom ON listings USING GIST(geom);
CREATE INDEX idx_kaveri_geom ON kaveri_registrations USING GIST(geom);
CREATE INDEX idx_regulatory_zones_geom ON regulatory_zones USING GIST(geom);
CREATE INDEX idx_overlay_constraints_geom ON overlay_constraints USING GIST(geom);
CREATE INDEX idx_infrastructure_geom ON infrastructure_pipeline USING GIST(geom);

-- ============================================================
-- STANDARD INDEXES
-- ============================================================
CREATE INDEX idx_rera_projects_market ON rera_projects(micro_market_id);
CREATE INDEX idx_rera_projects_developer ON rera_projects(developer_id);
CREATE INDEX idx_rera_projects_status ON rera_projects(project_status);
CREATE INDEX idx_rera_projects_number ON rera_projects(rera_number);
CREATE INDEX idx_listings_market ON listings(micro_market_id);

-- Partial unique index on kaveri_registrations: enforce uniqueness only for non-empty
-- registration numbers. Empty strings (fallback/sample records) are allowed to coexist.
CREATE UNIQUE INDEX idx_kaveri_reg_unique
    ON kaveri_registrations(registration_number)
    WHERE registration_number IS NOT NULL AND registration_number != '';
CREATE INDEX idx_listings_type ON listings(transaction_type, property_type);
CREATE INDEX idx_listings_active ON listings(is_active, last_seen_at);
CREATE INDEX idx_kaveri_date ON kaveri_registrations(transaction_date);
CREATE INDEX idx_kaveri_market ON kaveri_registrations(micro_market_id);
CREATE INDEX idx_market_snapshots ON market_snapshots(micro_market_id, snapshot_date);
CREATE INDEX idx_agent_runs_status ON agent_runs(status, started_at);

-- Fuzzy search on project names and developer names
CREATE INDEX idx_rera_projects_name_trgm ON rera_projects USING GIN(project_name gin_trgm_ops);
CREATE INDEX idx_developers_name_trgm ON developers USING GIN(name gin_trgm_ops);

-- ============================================================
-- SEED DATA — MICRO MARKETS (Bengaluru)
-- North corridor first, then expand
-- ============================================================
INSERT INTO micro_markets (name, slug, city, state, priority) VALUES
    -- North (Primary focus — Yelahanka corridor)
    ('Yelahanka', 'yelahanka', 'Bengaluru', 'Karnataka', 1),
    ('Devanahalli', 'devanahalli', 'Bengaluru', 'Karnataka', 1),
    ('Hebbal', 'hebbal', 'Bengaluru', 'Karnataka', 1),
    ('Jakkur', 'jakkur', 'Bengaluru', 'Karnataka', 1),
    ('Thanisandra', 'thanisandra', 'Bengaluru', 'Karnataka', 1),
    ('Kogilu', 'kogilu', 'Bengaluru', 'Karnataka', 1),
    ('Bagalur', 'bagalur', 'Bengaluru', 'Karnataka', 1),
    ('Doddaballapur Road', 'doddaballapur-road', 'Bengaluru', 'Karnataka', 0),

    -- East
    ('Whitefield', 'whitefield', 'Bengaluru', 'Karnataka', 0),
    ('Sarjapur Road', 'sarjapur-road', 'Bengaluru', 'Karnataka', 0),
    ('Marathahalli', 'marathahalli', 'Bengaluru', 'Karnataka', 0),
    ('Varthur', 'varthur', 'Bengaluru', 'Karnataka', 0),

    -- South
    ('Electronic City', 'electronic-city', 'Bengaluru', 'Karnataka', 0),
    ('Bannerghatta Road', 'bannerghatta-road', 'Bengaluru', 'Karnataka', 0),
    ('Kanakapura Road', 'kanakapura-road', 'Bengaluru', 'Karnataka', 0),

    -- West/Southwest
    ('Mysuru Road', 'mysuru-road', 'Bengaluru', 'Karnataka', 0),
    ('Kengeri', 'kengeri', 'Bengaluru', 'Karnataka', 0),

    -- Peripheral
    ('Nandi Hills Corridor', 'nandi-hills-corridor', 'Bengaluru', 'Karnataka', 0),
    ('Nelamangala', 'nelamangala', 'Bengaluru', 'Karnataka', 0),
    ('Hoskote', 'hoskote', 'Bengaluru', 'Karnataka', 0);

-- ============================================================
-- VIEWS — Useful pre-built queries
-- ============================================================

-- Active RERA projects with developer and market name
CREATE VIEW v_active_projects AS
SELECT
    r.rera_number,
    r.project_name,
    d.name AS developer_name,
    d.grade AS developer_grade,
    m.name AS micro_market,
    r.project_type,
    r.total_units,
    r.sold_units,
    r.unsold_units,
    r.absorption_pct,
    r.price_min_psf,
    r.price_max_psf,
    r.possession_date,
    r.project_status,
    r.locality,
    r.last_scraped_at
FROM rera_projects r
LEFT JOIN developers d ON r.developer_id = d.id
LEFT JOIN micro_markets m ON r.micro_market_id = m.id
WHERE r.is_active = TRUE;

-- Micro-market inventory summary
CREATE VIEW v_market_inventory AS
SELECT
    m.name AS micro_market,
    COUNT(r.id) AS total_projects,
    SUM(r.total_units) AS total_units,
    SUM(r.sold_units) AS total_sold,
    SUM(r.unsold_units) AS total_unsold,
    ROUND(AVG(r.absorption_pct), 1) AS avg_absorption_pct,
    ROUND(AVG(r.price_min_psf), 0) AS avg_min_psf,
    ROUND(AVG(r.price_max_psf), 0) AS avg_max_psf,
    COUNT(DISTINCT r.developer_id) AS unique_developers
FROM micro_markets m
LEFT JOIN rera_projects r ON r.micro_market_id = m.id AND r.is_active = TRUE
GROUP BY m.name, m.id
ORDER BY total_units DESC NULLS LAST;

-- Single-query market brief — analyst reads this instead of 3 separate queries
CREATE VIEW v_market_brief AS
SELECT
    m.name                                                         AS micro_market,
    COUNT(r.id)                                                    AS total_projects,
    SUM(r.total_units)                                             AS total_units,
    SUM(r.sold_units)                                              AS total_sold,
    SUM(r.unsold_units)                                            AS total_unsold,
    ROUND(AVG(r.absorption_pct), 1)                                AS avg_absorption_pct,
    ROUND(AVG(r.price_min_psf), 0)                                 AS avg_min_psf,
    ROUND(AVG(r.price_max_psf), 0)                                 AS avg_max_psf,
    COUNT(DISTINCT r.developer_id)                                 AS unique_developers,
    COUNT(DISTINCT CASE WHEN d.grade = 'A' THEN d.id END)          AS grade_a_developers,
    COUNT(DISTINCT CASE WHEN d.grade = 'B' THEN d.id END)          AS grade_b_developers,
    COUNT(CASE WHEN r.absorption_pct < 30
                    AND r.total_units > 100 THEN 1 END)            AS low_absorption_projects,
    COUNT(CASE WHEN r.possession_date < CURRENT_DATE
                    AND r.unsold_units > 50 THEN 1 END)            AS overdue_high_unsold_projects,
    ROUND(MIN(r.price_min_psf), 0)                                 AS floor_psf,
    ROUND(MAX(r.price_max_psf), 0)                                 AS ceiling_psf,
    MAX(r.last_scraped_at)                                         AS data_as_of
FROM micro_markets m
LEFT JOIN rera_projects r  ON r.micro_market_id = m.id AND r.is_active = TRUE
LEFT JOIN developers d     ON r.developer_id = d.id
GROUP BY m.name, m.id
ORDER BY total_units DESC NULLS LAST;

-- Developer performance scorecard
CREATE VIEW v_developer_scorecard AS
SELECT
    d.name AS developer,
    d.grade,
    COUNT(r.id) AS total_projects,
    SUM(r.total_units) AS total_units,
    ROUND(AVG(r.absorption_pct), 1) AS avg_absorption_pct,
    COUNT(CASE WHEN r.project_status = 'Completed' THEN 1 END) AS completed,
    COUNT(CASE WHEN r.delay_months > 0 THEN 1 END) AS delayed,
    ROUND(AVG(r.delay_months), 1) AS avg_delay_months,
    STRING_AGG(DISTINCT mm.name, ', ') AS markets_active_in
FROM developers d
LEFT JOIN rera_projects r ON r.developer_id = d.id
LEFT JOIN micro_markets mm ON r.micro_market_id = mm.id
GROUP BY d.id, d.name, d.grade
ORDER BY total_units DESC NULLS LAST;
