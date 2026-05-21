"""RE_OS core SQLAlchemy models (phase-1 baseline)."""

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class MicroMarket(Base):
    __tablename__ = "micro_markets"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
    city = Column(String(50), nullable=False, server_default="Bengaluru")
    state = Column(String(50), nullable=False, server_default="Karnataka")
    priority = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now())


class Developer(Base):
    __tablename__ = "developers"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name = Column(String(200), nullable=False)
    name_normalized = Column(String(200), unique=True)
    rera_promoter_id = Column(String(100))
    grade = Column(String(1))
    total_projects = Column(Integer, nullable=False, server_default="0")
    completed_projects = Column(Integer, nullable=False, server_default="0")
    delayed_projects = Column(Integer, nullable=False, server_default="0")
    avg_delay_months = Column(DECIMAL(5, 2))
    total_units_launched = Column(Integer, nullable=False, server_default="0")
    total_units_sold = Column(Integer, nullable=False, server_default="0")
    absorption_rate_pct = Column(DECIMAL(5, 2))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now())


class ReraProject(Base):
    __tablename__ = "rera_projects"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    rera_number = Column(String(100), nullable=False, unique=True)
    project_name = Column(String(300), nullable=False)
    developer_id = Column(UUID(as_uuid=True), ForeignKey("developers.id"))
    micro_market_id = Column(UUID(as_uuid=True), ForeignKey("micro_markets.id"))
    address = Column(Text)
    district = Column(String(100))
    taluk = Column(String(100))
    locality = Column(String(200))
    pincode = Column(String(10))
    project_type = Column(String(50))
    project_category = Column(String(50))
    total_units = Column(Integer)
    sold_units = Column(Integer)
    unsold_units = Column(Integer)
    blocked_units = Column(Integer, nullable=False, server_default="0")
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
    delay_months = Column(Integer, nullable=False, server_default="0")
    completion_pct = Column(DECIMAL(5, 2))
    project_status = Column(String(512))
    rera_status = Column(String(50))
    is_active = Column(Boolean, nullable=False, server_default="true")
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
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')",
            name="ck_rera_projects_data_source",
        ),
    )


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
    listed_at = Column(Date)
    first_seen_at = Column(DateTime, nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime, nullable=False, server_default=func.now())
    is_active = Column(Boolean, nullable=False, server_default="true")
    days_on_market = Column(Integer)
    is_new_launch = Column(Boolean, nullable=False, server_default="false")
    is_rera_registered = Column(Boolean)
    raw_rera_number = Column(String(100))
    raw_data = Column(JSONB)
    data_source = Column(String(20), nullable=False, server_default="seed_estimated")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "source_listing_id", name="uq_listings_source_listing"),
        CheckConstraint(
            "data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')",
            name="ck_listings_data_source",
        ),
    )


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
    stamp_duty_paid = Column(DECIMAL(12, 2))
    registration_fee = Column(DECIMAL(10, 2))
    buyer_name = Column(String(200))
    seller_name = Column(String(200))
    survey_number = Column(String(100))
    village = Column(String(100))
    hobli = Column(String(100))
    taluk = Column(String(100))
    district = Column(String(100))
    transaction_date = Column(Date)
    registration_date = Column(Date)
    raw_data = Column(JSONB)
    data_source = Column(String(20), nullable=False, server_default="seed_estimated")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')",
            name="ck_kaveri_reg_data_source",
        ),
    )


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
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')",
            name="ck_guidance_values_data_source",
        ),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    agent_name = Column(String(100), nullable=False)
    task_type = Column(String(100), nullable=False)
    micro_market = Column(String(100))
    status = Column(String(50), nullable=False, server_default="started")
    records_scraped = Column(Integer, nullable=False, server_default="0")
    records_inserted = Column(Integer, nullable=False, server_default="0")
    records_updated = Column(Integer, nullable=False, server_default="0")
    records_failed = Column(Integer, nullable=False, server_default="0")
    error_message = Column(Text)
    metadata_json = Column("metadata", JSONB)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime)
    duration_seconds = Column(Integer)


class AgentMemory(Base):
    __tablename__ = "agent_memories"

    memory_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    agent_id = Column(Text, nullable=False)
    market = Column(Text)
    fact = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False, server_default="0.6")
    source_count = Column(Integer, nullable=False, server_default="1")
    last_confirmed = Column(Date, nullable=False, server_default=func.current_date())
    superseded_by = Column(UUID(as_uuid=True), ForeignKey("agent_memories.memory_id"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="ck_agent_memories_confidence"),
    )


class BoardSession(Base):
    __tablename__ = "board_sessions"

    session_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    market = Column(Text, nullable=False)
    initiated_by = Column(Text, nullable=False, server_default="ceo")
    pitch_text = Column(Text)
    status = Column(Text, nullable=False, server_default="pending")
    bd_response = Column(Text)
    finance_response = Column(Text)
    engineering_response = Column(Text)
    ops_response = Column(Text)
    ceo_synthesis = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'active', 'complete', 'failed')", name="ck_board_sessions_status"),
    )
