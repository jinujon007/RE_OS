"""
SQLAlchemy ORM models for RE_OS database.

Maps all 15 tables defined in database/schema.sql.
Uses SQLAlchemy 2.x DeclarativeBase API.

PostGIS GEOMETRY columns are mapped as String — install GeoAlchemy2 for spatial ops.
GENERATED ALWAYS AS columns (absorption_pct, guidance_market_gap_pct) are read-only;
do not include them in INSERT/UPDATE payloads.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    DECIMAL,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# micro_markets
# ---------------------------------------------------------------------------


class MicroMarket(Base):
    __tablename__ = "micro_markets"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    city = Column(String(50), nullable=False, server_default="Bengaluru")
    state = Column(String(50), nullable=False, server_default="Karnataka")
    geom = Column(String)  # GEOMETRY(POLYGON, 4326) — use GeoAlchemy2 for spatial ops
    centroid = Column(String)  # GEOMETRY(POINT, 4326)
    priority = Column(Integer, server_default="0")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    rera_projects = relationship("ReraProject", back_populates="micro_market")
    listings = relationship("Listing", back_populates="micro_market")
    kaveri_registrations = relationship("KaveriRegistration", back_populates="micro_market")
    guidance_values = relationship("GuidanceValue", back_populates="micro_market")
    market_snapshots = relationship("MarketSnapshot", back_populates="micro_market")
    news_articles = relationship("NewsArticle", back_populates="micro_market")


# ---------------------------------------------------------------------------
# developers
# ---------------------------------------------------------------------------


class Developer(Base):
    __tablename__ = "developers"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(String(200), nullable=False)
    name_normalized = Column(String(200), unique=True)
    rera_promoter_id = Column(String(100))
    grade = Column(String(1))
    total_projects = Column(Integer, server_default="0")
    completed_projects = Column(Integer, server_default="0")
    delayed_projects = Column(Integer, server_default="0")
    avg_delay_months = Column(DECIMAL(5, 2))
    total_units_launched = Column(Integer, server_default="0")
    total_units_sold = Column(Integer, server_default="0")
    absorption_rate_pct = Column(DECIMAL(5, 2))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    rera_projects = relationship("ReraProject", back_populates="developer")


# ---------------------------------------------------------------------------
# rera_projects
# ---------------------------------------------------------------------------


class ReraProject(Base):
    __tablename__ = "rera_projects"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    rera_number = Column(String(100), unique=True, nullable=False)
    project_name = Column(String(300), nullable=False)
    developer_id = Column(UUID(as_uuid=True), ForeignKey("developers.id"))
    micro_market_id = Column(UUID(as_uuid=True), ForeignKey("micro_markets.id"))

    address = Column(Text)
    district = Column(String(100))
    taluk = Column(String(100))
    locality = Column(String(200))
    pincode = Column(String(10))
    geom = Column(String)  # GEOMETRY(POINT, 4326)

    project_type = Column(String(50))
    project_category = Column(String(50))

    total_units = Column(Integer)
    sold_units = Column(Integer)
    unsold_units = Column(Integer)
    blocked_units = Column(Integer, server_default="0")
    absorption_pct = Column(DECIMAL(5, 2))  # GENERATED ALWAYS AS — read-only

    total_land_area_sqm = Column(DECIMAL(12, 2))
    total_built_up_area_sqm = Column(DECIMAL(12, 2))

    price_min_psf = Column(DECIMAL(10, 2))
    price_max_psf = Column(DECIMAL(10, 2))
    price_avg_psf = Column(DECIMAL(10, 2))

    unit_mix = Column(JSONB)
    amenities = Column(JSONB)

    launch_date = Column(Date)
    registration_date = Column(Date)
    possession_date = Column(Date)
    plan_approval_date = Column(Date)
    rera_expiry_date = Column(Date)
    actual_completion_date = Column(Date)
    delay_months = Column(Integer, server_default="0")
    completion_pct = Column(DECIMAL(5, 2))

    project_status = Column(String(512))
    rera_status = Column(String(50))
    is_active = Column(Boolean, server_default="true")

    estimated_project_cost = Column(DECIMAL(15, 2))
    amount_collected = Column(DECIMAL(15, 2))

    architect_name = Column(String(200))
    ca_name = Column(String(200))
    structural_engineer = Column(String(200))

    raw_data = Column(JSONB)
    detail_url = Column(Text)
    source_url = Column(Text)
    last_scraped_at = Column(DateTime)
    data_source = Column(String(20), nullable=False, server_default="seed_estimated")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    developer = relationship("Developer", back_populates="rera_projects")
    micro_market = relationship("MicroMarket", back_populates="rera_projects")
    snapshots = relationship(
        "ProjectSnapshot", back_populates="rera_project", cascade="all, delete-orphan"
    )
    listings = relationship("Listing", back_populates="rera_project")
    kaveri_registrations = relationship("KaveriRegistration", back_populates="rera_project")

    __table_args__ = (
        CheckConstraint(
            "data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')",
            name="ck_rera_projects_data_source",
        ),
    )


# ---------------------------------------------------------------------------
# project_snapshots
# ---------------------------------------------------------------------------


class ProjectSnapshot(Base):
    __tablename__ = "project_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    rera_project_id = Column(
        UUID(as_uuid=True), ForeignKey("rera_projects.id", ondelete="CASCADE")
    )
    snapshot_date = Column(Date, nullable=False)
    sold_units = Column(Integer)
    unsold_units = Column(Integer)
    price_min_psf = Column(DECIMAL(10, 2))
    price_max_psf = Column(DECIMAL(10, 2))
    units_sold_this_period = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())

    rera_project = relationship("ReraProject", back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("rera_project_id", "snapshot_date", name="uq_project_snapshots"),
    )


# ---------------------------------------------------------------------------
# listings
# ---------------------------------------------------------------------------


class Listing(Base):
    __tablename__ = "listings"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    source = Column(String(50), nullable=False)
    source_listing_id = Column(String(200))
    source_url = Column(Text)
    micro_market_id = Column(UUID(as_uuid=True), ForeignKey("micro_markets.id"))
    rera_project_id = Column(UUID(as_uuid=True), ForeignKey("rera_projects.id"))

    property_type = Column(String(50))
    transaction_type = Column(String(20))
    bhk_config = Column(String(30))

    carpet_area_sqft = Column(DECIMAL(10, 2))
    built_up_area_sqft = Column(DECIMAL(10, 2))
    super_built_up_sqft = Column(DECIMAL(10, 2))
    plot_area_sqft = Column(DECIMAL(10, 2))

    listed_price = Column(DECIMAL(15, 2))
    price_psf = Column(DECIMAL(10, 2))
    monthly_rent = Column(DECIMAL(10, 2))
    security_deposit = Column(DECIMAL(10, 2))
    deposit_months = Column(DECIMAL(4, 1))

    address = Column(Text)
    locality = Column(String(200))
    geom = Column(String)  # GEOMETRY(POINT, 4326)

    listed_at = Column(Date)
    first_seen_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime, server_default=func.now())
    is_active = Column(Boolean, server_default="true")
    days_on_market = Column(Integer)

    is_new_launch = Column(Boolean, server_default="false")
    is_rera_registered = Column(Boolean)
    raw_rera_number = Column(String(100))

    raw_data = Column(JSONB)
    data_source = Column(String(20), nullable=False, server_default="seed_estimated")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    micro_market = relationship("MicroMarket", back_populates="listings")
    rera_project = relationship("ReraProject", back_populates="listings")

    __table_args__ = (
        UniqueConstraint("source", "source_listing_id", name="uq_listings_source"),
        CheckConstraint(
            "data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')",
            name="ck_listings_data_source",
        ),
    )


# ---------------------------------------------------------------------------
# kaveri_registrations
# ---------------------------------------------------------------------------


class KaveriRegistration(Base):
    __tablename__ = "kaveri_registrations"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    registration_number = Column(String(200))
    document_number = Column(String(200))
    micro_market_id = Column(UUID(as_uuid=True), ForeignKey("micro_markets.id"))
    rera_project_id = Column(UUID(as_uuid=True), ForeignKey("rera_projects.id"))

    property_type = Column(String(50))
    property_description = Column(Text)
    area_sqft = Column(DECIMAL(10, 2))
    area_sqm = Column(DECIMAL(10, 2))

    transaction_amount = Column(DECIMAL(15, 2))
    guidance_value = Column(DECIMAL(15, 2))
    guidance_market_gap_pct = Column(DECIMAL(5, 2))  # GENERATED ALWAYS AS — read-only
    stamp_duty_paid = Column(DECIMAL(12, 2))
    registration_fee = Column(DECIMAL(10, 2))

    buyer_name = Column(String(200))
    seller_name = Column(String(200))

    survey_number = Column(String(100))
    village = Column(String(100))
    hobli = Column(String(100))
    taluk = Column(String(100))
    district = Column(String(100))
    geom = Column(String)  # GEOMETRY(POINT, 4326)

    transaction_date = Column(Date)
    registration_date = Column(Date)

    raw_data = Column(JSONB)
    data_source = Column(String(20), nullable=False, server_default="seed_estimated")
    created_at = Column(DateTime, server_default=func.now())

    micro_market = relationship("MicroMarket", back_populates="kaveri_registrations")
    rera_project = relationship("ReraProject", back_populates="kaveri_registrations")

    __table_args__ = (
        CheckConstraint(
            "data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')",
            name="ck_kaveri_data_source",
        ),
    )


# ---------------------------------------------------------------------------
# guidance_values
# ---------------------------------------------------------------------------


class GuidanceValue(Base):
    __tablename__ = "guidance_values"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    micro_market_id = Column(UUID(as_uuid=True), ForeignKey("micro_markets.id"))
    locality = Column(String(200))
    area_code = Column(String(50))
    property_type = Column(String(50))
    road_type = Column(String(50))
    guidance_value_psf = Column(DECIMAL(10, 2))
    guidance_value_per_sqm = Column(DECIMAL(10, 2))
    effective_from = Column(Date)
    effective_to = Column(Date)
    source_document = Column(Text)
    data_source = Column(String(20), nullable=False, server_default="seed_estimated")
    created_at = Column(DateTime, server_default=func.now())

    micro_market = relationship("MicroMarket", back_populates="guidance_values")

    __table_args__ = (
        CheckConstraint(
            "data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')",
            name="ck_guidance_values_data_source",
        ),
    )


# ---------------------------------------------------------------------------
# regulatory_zones
# ---------------------------------------------------------------------------


class RegulatoryZone(Base):
    __tablename__ = "regulatory_zones"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    authority = Column(String(50), nullable=False)
    zone_type = Column(String(50), nullable=False)
    zone_code = Column(String(20))
    zone_description = Column(String(200))

    far_base = Column(DECIMAL(5, 2))
    far_road_9m = Column(DECIMAL(5, 2))
    far_road_12m = Column(DECIMAL(5, 2))
    far_road_18m = Column(DECIMAL(5, 2))
    far_road_24m = Column(DECIMAL(5, 2))
    far_road_30m_plus = Column(DECIMAL(5, 2))

    front_setback_m = Column(DECIMAL(5, 2))
    side_setback_m = Column(DECIMAL(5, 2))
    rear_setback_m = Column(DECIMAL(5, 2))

    max_height_m = Column(DECIMAL(5, 2))
    ground_coverage_pct = Column(DECIMAL(5, 2))
    mixed_use_permitted = Column(Boolean, server_default="false")
    commercial_pct_permitted = Column(DECIMAL(5, 2))

    parking_norm_per_unit = Column(String(100))

    geom = Column(String)  # GEOMETRY(MULTIPOLYGON, 4326)
    dc_rules_reference = Column(String(200))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# overlay_constraints
# ---------------------------------------------------------------------------


class OverlayConstraint(Base):
    __tablename__ = "overlay_constraints"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    constraint_type = Column(String(100), nullable=False)
    authority = Column(String(100))
    buffer_distance_m = Column(DECIMAL(10, 2))
    description = Column(Text)
    geom = Column(String)  # GEOMETRY(GEOMETRY, 4326)
    source_document = Column(Text)
    notified_date = Column(Date)
    created_at = Column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# infrastructure_pipeline
# ---------------------------------------------------------------------------


class InfrastructurePipeline(Base):
    __tablename__ = "infrastructure_pipeline"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(String(300), nullable=False)
    infra_type = Column(String(50), nullable=False)
    authority = Column(String(100))
    project_status = Column(String(50))
    geom = Column(String)  # GEOMETRY(GEOMETRY, 4326)

    announced_date = Column(Date)
    tender_date = Column(Date)
    construction_start = Column(Date)
    expected_completion = Column(Date)
    actual_completion = Column(Date)

    impact_radius_km = Column(DECIMAL(5, 2), server_default="1.0")

    description = Column(Text)
    source_url = Column(Text)
    raw_data = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------------------
# market_snapshots
# ---------------------------------------------------------------------------


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    micro_market_id = Column(UUID(as_uuid=True), ForeignKey("micro_markets.id"))
    snapshot_date = Column(Date, nullable=False)
    period = Column(String(20), server_default="monthly")

    avg_psf_sale = Column(DECIMAL(10, 2))
    median_psf_sale = Column(DECIMAL(10, 2))
    min_psf_sale = Column(DECIMAL(10, 2))
    max_psf_sale = Column(DECIMAL(10, 2))
    avg_psf_rent = Column(DECIMAL(10, 2))
    avg_rent_2bhk = Column(DECIMAL(10, 2))
    avg_rent_3bhk = Column(DECIMAL(10, 2))

    total_rera_projects = Column(Integer)
    active_rera_projects = Column(Integer)
    total_rera_units = Column(Integer)
    sold_rera_units = Column(Integer)
    unsold_rera_units = Column(Integer)
    avg_absorption_pct = Column(DECIMAL(5, 2))

    total_active_listings = Column(Integer)
    new_listings_this_period = Column(Integer)
    listings_2bhk = Column(Integer)
    listings_3bhk = Column(Integer)

    registrations_this_period = Column(Integer)
    avg_transaction_psf = Column(DECIMAL(10, 2))
    avg_guidance_value_psf = Column(DECIMAL(10, 2))
    avg_guidance_market_gap_pct = Column(DECIMAL(5, 2))

    active_developers = Column(Integer)
    grade_a_developers = Column(Integer)
    grade_b_developers = Column(Integer)
    new_launches_this_period = Column(Integer)

    market_summary = Column(Text)
    key_signals = Column(JSONB)
    risk_flags = Column(JSONB)

    created_at = Column(DateTime, server_default=func.now())

    micro_market = relationship("MicroMarket", back_populates="market_snapshots")

    __table_args__ = (
        UniqueConstraint(
            "micro_market_id", "snapshot_date", "period", name="uq_market_snapshots"
        ),
    )


# ---------------------------------------------------------------------------
# news_articles
# ---------------------------------------------------------------------------


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    cid = Column(String(100), unique=True, nullable=False)
    title = Column(Text, nullable=False)
    source = Column(String(100))
    source_url = Column(Text)
    published_at = Column(Date)
    summary = Column(Text)
    signal_type = Column(String(50))
    key_insight = Column(Text)
    micro_market_id = Column(UUID(as_uuid=True), ForeignKey("micro_markets.id"))
    raw_data = Column(JSONB)
    created_at = Column(DateTime, server_default=func.now())

    micro_market = relationship("MicroMarket", back_populates="news_articles")


# ---------------------------------------------------------------------------
# agent_runs
# ---------------------------------------------------------------------------


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    agent_name = Column(String(100), nullable=False)
    task_type = Column(String(100), nullable=False)
    micro_market = Column(String(100))
    status = Column(String(50), server_default="started")
    records_scraped = Column(Integer, server_default="0")
    records_inserted = Column(Integer, server_default="0")
    records_updated = Column(Integer, server_default="0")
    records_failed = Column(Integer, server_default="0")
    error_message = Column(Text)
    metadata = Column(JSONB)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    duration_seconds = Column(Integer)


# ---------------------------------------------------------------------------
# agent_memories
# ---------------------------------------------------------------------------


class AgentMemory(Base):
    __tablename__ = "agent_memories"

    memory_id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    agent_id = Column(Text, nullable=False)
    market = Column(Text)
    fact = Column(Text, nullable=False)
    confidence = Column(Float, server_default="0.6")
    source_count = Column(Integer, server_default="1")
    last_confirmed = Column(Date, server_default=func.current_date())
    superseded_by = Column(UUID(as_uuid=True), ForeignKey("agent_memories.memory_id"))
    created_at = Column(TIMESTAMPTZ, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "confidence BETWEEN 0.0 AND 1.0", name="ck_agent_memories_confidence"
        ),
    )


# ---------------------------------------------------------------------------
# board_sessions
# ---------------------------------------------------------------------------


class BoardSession(Base):
    __tablename__ = "board_sessions"

    session_id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    market = Column(Text, nullable=False)
    initiated_by = Column(Text, nullable=False, server_default="ceo")
    pitch_text = Column(Text)
    status = Column(Text, nullable=False, server_default="pending")
    bd_response = Column(Text)
    finance_response = Column(Text)
    engineering_response = Column(Text)
    ops_response = Column(Text)
    ceo_synthesis = Column(Text)
    created_at = Column(TIMESTAMPTZ, server_default=func.now())
    completed_at = Column(TIMESTAMPTZ)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'complete', 'failed')",
            name="ck_board_sessions_status",
        ),
    )
