"""initial core schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "micro_markets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("city", sa.String(length=50), nullable=False, server_default=sa.text("'Bengaluru'")),
        sa.Column("state", sa.String(length=50), nullable=False, server_default=sa.text("'Karnataka'")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_micro_markets_slug"),
    )

    op.create_table(
        "developers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_normalized", sa.String(length=200), nullable=True),
        sa.Column("rera_promoter_id", sa.String(length=100), nullable=True),
        sa.Column("grade", sa.String(length=1), nullable=True),
        sa.Column("total_projects", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completed_projects", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("delayed_projects", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_delay_months", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("total_units_launched", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_units_sold", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("absorption_rate_pct", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_normalized", name="uq_developers_name_normalized"),
    )

    op.create_table(
        "rera_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("rera_number", sa.String(length=100), nullable=False),
        sa.Column("project_name", sa.String(length=300), nullable=False),
        sa.Column("developer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("district", sa.String(length=100), nullable=True),
        sa.Column("taluk", sa.String(length=100), nullable=True),
        sa.Column("locality", sa.String(length=200), nullable=True),
        sa.Column("pincode", sa.String(length=10), nullable=True),
        sa.Column("project_type", sa.String(length=50), nullable=True),
        sa.Column("project_category", sa.String(length=50), nullable=True),
        sa.Column("total_units", sa.Integer(), nullable=True),
        sa.Column("sold_units", sa.Integer(), nullable=True),
        sa.Column("unsold_units", sa.Integer(), nullable=True),
        sa.Column("blocked_units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_land_area_sqm", sa.DECIMAL(12, 2), nullable=True),
        sa.Column("total_built_up_area_sqm", sa.DECIMAL(12, 2), nullable=True),
        sa.Column("price_min_psf", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("price_max_psf", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("price_avg_psf", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("unit_mix", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("amenities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("launch_date", sa.Date(), nullable=True),
        sa.Column("registration_date", sa.Date(), nullable=True),
        sa.Column("possession_date", sa.Date(), nullable=True),
        sa.Column("plan_approval_date", sa.Date(), nullable=True),
        sa.Column("rera_expiry_date", sa.Date(), nullable=True),
        sa.Column("actual_completion_date", sa.Date(), nullable=True),
        sa.Column("delay_months", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completion_pct", sa.DECIMAL(5, 2), nullable=True),
        sa.Column("project_status", sa.String(length=512), nullable=True),
        sa.Column("rera_status", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("estimated_project_cost", sa.DECIMAL(15, 2), nullable=True),
        sa.Column("amount_collected", sa.DECIMAL(15, 2), nullable=True),
        sa.Column("architect_name", sa.String(length=200), nullable=True),
        sa.Column("ca_name", sa.String(length=200), nullable=True),
        sa.Column("structural_engineer", sa.String(length=200), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("detail_url", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("last_scraped_at", sa.DateTime(), nullable=True),
        sa.Column("data_source", sa.String(length=20), nullable=False, server_default=sa.text("'seed_estimated'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')", name="ck_rera_projects_data_source"),
        sa.ForeignKeyConstraint(["developer_id"], ["developers.id"]),
        sa.ForeignKeyConstraint(["micro_market_id"], ["micro_markets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rera_number", name="uq_rera_projects_rera_number"),
    )

    op.create_table(
        "listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_listing_id", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rera_project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_type", sa.String(length=50), nullable=True),
        sa.Column("transaction_type", sa.String(length=20), nullable=True),
        sa.Column("bhk_config", sa.String(length=30), nullable=True),
        sa.Column("carpet_area_sqft", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("built_up_area_sqft", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("super_built_up_sqft", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("plot_area_sqft", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("listed_price", sa.DECIMAL(15, 2), nullable=True),
        sa.Column("price_psf", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("monthly_rent", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("security_deposit", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("deposit_months", sa.DECIMAL(4, 1), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("locality", sa.String(length=200), nullable=True),
        sa.Column("listed_at", sa.Date(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("days_on_market", sa.Integer(), nullable=True),
        sa.Column("is_new_launch", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_rera_registered", sa.Boolean(), nullable=True),
        sa.Column("raw_rera_number", sa.String(length=100), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("data_source", sa.String(length=20), nullable=False, server_default=sa.text("'seed_estimated'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')", name="ck_listings_data_source"),
        sa.ForeignKeyConstraint(["micro_market_id"], ["micro_markets.id"]),
        sa.ForeignKeyConstraint(["rera_project_id"], ["rera_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_listing_id", name="uq_listings_source_listing"),
    )

    op.create_table(
        "kaveri_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("registration_number", sa.String(length=200), nullable=True),
        sa.Column("document_number", sa.String(length=200), nullable=True),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rera_project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_type", sa.String(length=50), nullable=True),
        sa.Column("property_description", sa.Text(), nullable=True),
        sa.Column("area_sqft", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("area_sqm", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("transaction_amount", sa.DECIMAL(15, 2), nullable=True),
        sa.Column("guidance_value", sa.DECIMAL(15, 2), nullable=True),
        sa.Column("stamp_duty_paid", sa.DECIMAL(12, 2), nullable=True),
        sa.Column("registration_fee", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("buyer_name", sa.String(length=200), nullable=True),
        sa.Column("seller_name", sa.String(length=200), nullable=True),
        sa.Column("survey_number", sa.String(length=100), nullable=True),
        sa.Column("village", sa.String(length=100), nullable=True),
        sa.Column("hobli", sa.String(length=100), nullable=True),
        sa.Column("taluk", sa.String(length=100), nullable=True),
        sa.Column("district", sa.String(length=100), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("registration_date", sa.Date(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("data_source", sa.String(length=20), nullable=False, server_default=sa.text("'seed_estimated'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')", name="ck_kaveri_reg_data_source"),
        sa.ForeignKeyConstraint(["micro_market_id"], ["micro_markets.id"]),
        sa.ForeignKeyConstraint(["rera_project_id"], ["rera_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "guidance_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("locality", sa.String(length=200), nullable=True),
        sa.Column("area_code", sa.String(length=50), nullable=True),
        sa.Column("property_type", sa.String(length=50), nullable=True),
        sa.Column("road_type", sa.String(length=50), nullable=True),
        sa.Column("guidance_value_psf", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("guidance_value_per_sqm", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source_document", sa.Text(), nullable=True),
        sa.Column("data_source", sa.String(length=20), nullable=False, server_default=sa.text("'seed_estimated'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("data_source IN ('portal_scraped', 'seed_estimated', 'manual_entry')", name="ck_guidance_values_data_source"),
        sa.ForeignKeyConstraint(["micro_market_id"], ["micro_markets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("micro_market", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'started'")),
        sa.Column("records_scraped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("records_inserted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("records_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent_memories",
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("market", sa.Text(), nullable=True),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0.6")),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_confirmed", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("superseded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="ck_agent_memories_confidence"),
        sa.ForeignKeyConstraint(["superseded_by"], ["agent_memories.memory_id"]),
        sa.PrimaryKeyConstraint("memory_id"),
    )

    op.create_table(
        "board_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("initiated_by", sa.Text(), nullable=False, server_default=sa.text("'ceo'")),
        sa.Column("pitch_text", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("bd_response", sa.Text(), nullable=True),
        sa.Column("finance_response", sa.Text(), nullable=True),
        sa.Column("engineering_response", sa.Text(), nullable=True),
        sa.Column("ops_response", sa.Text(), nullable=True),
        sa.Column("ceo_synthesis", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'active', 'complete', 'failed')", name="ck_board_sessions_status"),
        sa.PrimaryKeyConstraint("session_id"),
    )

    op.create_index("idx_agent_runs_status", "agent_runs", ["status", "started_at"], unique=False)
    op.create_index("idx_kaveri_market", "kaveri_registrations", ["micro_market_id"], unique=False)
    op.create_index("idx_rera_projects_market", "rera_projects", ["micro_market_id"], unique=False)
    op.create_index("idx_rera_projects_developer", "rera_projects", ["developer_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_rera_projects_developer", table_name="rera_projects")
    op.drop_index("idx_rera_projects_market", table_name="rera_projects")
    op.drop_index("idx_kaveri_market", table_name="kaveri_registrations")
    op.drop_index("idx_agent_runs_status", table_name="agent_runs")

    op.drop_table("board_sessions")
    op.drop_table("agent_memories")
    op.drop_table("agent_runs")
    op.drop_table("guidance_values")
    op.drop_table("kaveri_registrations")
    op.drop_table("listings")
    op.drop_table("rera_projects")
    op.drop_table("developers")
    op.drop_table("micro_markets")
