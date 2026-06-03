"""v2 Schema — create all 15 new tables + indexes + T-709 composite index paths.
Revision ID: 0100_v2_schema
Revises: 0015_add_memory_fact_type
Create Date: 2026-06-02
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from geoalchemy2 import Geometry

revision: str = "0100_v2_schema"
down_revision: Union[str, None] = "0015_add_memory_fact_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── surveys ──────────────────────────────────────────────────────────────
    op.create_table("surveys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("survey_no", sa.String(100), nullable=False),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("micro_markets.id"), nullable=False),
        sa.Column("village", sa.String(200)),
        sa.Column("hobli", sa.String(200)),
        sa.Column("taluk", sa.String(200)),
        sa.Column("district", sa.String(100)),
        sa.Column("total_area_acres", sa.DECIMAL(12, 4)),
        sa.Column("total_area_sqft", sa.DECIMAL(14, 2)),
        sa.Column("geom", Geometry("POLYGON", 4326)),
        sa.Column("land_type", sa.String(50)),
        sa.Column("ownership_type", sa.String(50)),
        sa.Column("dc_conversion_status", sa.String(50)),
        sa.Column("dc_order_no", sa.String(100)),
        sa.Column("dc_order_date", sa.Date()),
        sa.Column("khata_no", sa.String(100)),
        sa.Column("khata_type", sa.String(50)),
        sa.Column("rtc_count", sa.Integer(), server_default="0"),
        sa.Column("litigation_count", sa.Integer(), server_default="0"),
        sa.Column("encumbrance_clear", sa.Boolean(), server_default="false"),
        sa.Column("is_aggregated", sa.Boolean(), server_default="false"),
        sa.Column("parent_survey_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("surveys.id")),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("survey_no", "micro_market_id"),
    )
    op.create_index("idx_surveys_market", "surveys", ["micro_market_id"])
    op.create_index("idx_surveys_survey_no", "surveys", ["survey_no"])
    op.create_index("idx_surveys_geom", "surveys", [sa.text("geom")], postgresql_using="gist")
    op.create_index("idx_surveys_parent", "surveys", ["parent_survey_id"])

    # ── rtc_records ──────────────────────────────────────────────────────────
    op.create_table("rtc_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("survey_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("surveys.id")),
        sa.Column("survey_no", sa.String(100), nullable=False),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("micro_markets.id")),
        sa.Column("owner_name", sa.Text()),
        sa.Column("owner_share", sa.DECIMAL(5, 2)),
        sa.Column("cultivation_status", sa.String(100)),
        sa.Column("crop_grown", sa.String(100)),
        sa.Column("irrigation_type", sa.String(100)),
        sa.Column("land_type", sa.String(100)),
        sa.Column("extent_acres", sa.DECIMAL(10, 4)),
        sa.Column("mutation_no", sa.String(100)),
        sa.Column("mutation_date", sa.Date()),
        sa.Column("rtc_period", sa.String(20)),
        sa.Column("rtc_year", sa.Integer()),
        sa.Column("source", sa.String(50), server_default="bhoomi_portal"),
        sa.Column("raw_data", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("survey_no", "rtc_period", "rtc_year"),
    )
    op.create_index("idx_rtc_survey", "rtc_records", ["survey_id"])
    op.create_index("idx_rtc_survey_no", "rtc_records", ["survey_no"])
    op.create_index("idx_rtc_market", "rtc_records", ["micro_market_id"])

    # ── khata_records ────────────────────────────────────────────────────────
    op.create_table("khata_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("khata_no", sa.String(100), nullable=False),
        sa.Column("khata_type", sa.String(50), nullable=False),
        sa.Column("survey_no", sa.String(100)),
        sa.Column("survey_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("surveys.id")),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("micro_markets.id")),
        sa.Column("property_address", sa.Text()),
        sa.Column("owner_name", sa.Text()),
        sa.Column("property_usage", sa.String(100)),
        sa.Column("zone", sa.String(50)),
        sa.Column("ward", sa.String(100)),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("source", sa.String(50), server_default="bbmp_portal"),
        sa.Column("raw_data", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("khata_no"),
    )
    op.create_index("idx_khata_survey", "khata_records", ["survey_id"])
    op.create_index("idx_khata_market", "khata_records", ["micro_market_id"])
    op.create_index("idx_khata_type", "khata_records", ["khata_type"])

    # ── litigations ──────────────────────────────────────────────────────────
    op.create_table("litigations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("case_no", sa.String(200), nullable=False),
        sa.Column("court_name", sa.String(200)),
        sa.Column("survey_no", sa.String(100)),
        sa.Column("survey_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("surveys.id")),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("micro_markets.id")),
        sa.Column("case_type", sa.String(100)),
        sa.Column("plaintiff_name", sa.Text()),
        sa.Column("defendant_name", sa.Text()),
        sa.Column("filing_date", sa.Date()),
        sa.Column("last_hearing_date", sa.Date()),
        sa.Column("next_hearing_date", sa.Date()),
        sa.Column("case_status", sa.String(100)),
        sa.Column("case_stage", sa.String(100)),
        sa.Column("description", sa.Text()),
        sa.Column("relief_sought", sa.Text()),
        sa.Column("is_encumbrance", sa.Boolean(), server_default="false"),
        sa.Column("source", sa.String(50), server_default="indiankanoon"),
        sa.Column("raw_data", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_litigations_survey", "litigations", ["survey_id"])
    op.create_index("idx_litigations_survey_no", "litigations", ["survey_no"])
    op.create_index("idx_litigations_market", "litigations", ["micro_market_id"])
    op.create_index("idx_litigations_status", "litigations", ["case_status"])

    # ── distressed_opps ──────────────────────────────────────────────────────
    op.create_table("distressed_opps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("developer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("developers.id")),
        sa.Column("developer_name", sa.String(200), nullable=False),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("micro_markets.id")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rera_projects.id")),
        sa.Column("distress_score", sa.DECIMAL(5, 2)),
        sa.Column("delay_months", sa.Integer()),
        sa.Column("incomplete_ratio", sa.DECIMAL(5, 2)),
        sa.Column("complaint_proxy", sa.DECIMAL(5, 2)),
        sa.Column("alert_level", sa.String(20), server_default="watch"),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("last_updated", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_actioned", sa.Boolean(), server_default="false"),
        sa.Column("actioned_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("notes", sa.Text()),
    )
    op.create_index("idx_distressed_dev", "distressed_opps", ["developer_id"])
    op.create_index("idx_distressed_score", "distressed_opps", [sa.text("distress_score DESC")])
    op.create_index("idx_distressed_market", "distressed_opps", ["micro_market_id"])
    op.create_index("idx_distressed_alert", "distressed_opps", ["alert_level"])

    # ── developer_health ─────────────────────────────────────────────────────
    op.create_table("developer_health",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("developer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("developers.id"), nullable=False, unique=True),
        sa.Column("developer_name", sa.String(200), nullable=False),
        sa.Column("health_score", sa.DECIMAL(5, 2)),
        sa.Column("financial_stability", sa.DECIMAL(5, 2)),
        sa.Column("project_completion_rate", sa.DECIMAL(5, 2)),
        sa.Column("avg_delay_months", sa.DECIMAL(5, 2)),
        sa.Column("legal_compliance_score", sa.DECIMAL(5, 2)),
        sa.Column("market_reputation", sa.String(50)),
        sa.Column("distress_signals", postgresql.JSONB()),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_dev_health_score", "developer_health", [sa.text("health_score DESC")])

    # ── demand_signals ───────────────────────────────────────────────────────
    op.create_table("demand_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("micro_markets.id"), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("median_days_on_market", sa.Integer()),
        sa.Column("slow_market_flag", sa.Boolean(), server_default="false"),
        sa.Column("fastest_config", sa.String(30)),
        sa.Column("dominant_ticket_size", sa.String(30)),
        sa.Column("nri_transaction_pct", sa.DECIMAL(5, 2)),
        sa.Column("price_revision_rate", sa.DECIMAL(5, 2)),
        sa.Column("absorption_rates", postgresql.JSONB()),
        sa.Column("source", sa.String(50), server_default="computed"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("micro_market_id", "signal_date"),
    )
    op.create_index("idx_demand_market", "demand_signals", ["micro_market_id", sa.text("signal_date DESC")])

    # ── deals ────────────────────────────────────────────────────────────────
    op.create_table("deals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("deal_name", sa.String(200), nullable=False),
        sa.Column("survey_no", sa.String(100)),
        sa.Column("survey_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("surveys.id")),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("micro_markets.id")),
        sa.Column("developer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("developers.id")),
        sa.Column("deal_type", sa.String(50), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False, server_default="identified"),
        sa.Column("area_acres", sa.DECIMAL(10, 4)),
        sa.Column("ask_psf", sa.DECIMAL(12, 2)),
        sa.Column("guidance_value_psf", sa.DECIMAL(12, 2)),
        sa.Column("negotiated_price", sa.DECIMAL(15, 2)),
        sa.Column("landowner_ratio", sa.DECIMAL(5, 2)),
        sa.Column("lls_equity_share", sa.DECIMAL(5, 2)),
        sa.Column("irr_base", sa.DECIMAL(5, 2)),
        sa.Column("irr_bull", sa.DECIMAL(5, 2)),
        sa.Column("irr_bear", sa.DECIMAL(5, 2)),
        sa.Column("verdict", sa.String(20)),
        sa.Column("deal_lead", sa.String(100)),
        sa.Column("contacted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("expected_close", sa.TIMESTAMP(timezone=True)),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_deals_market", "deals", ["micro_market_id"])
    op.create_index("idx_deals_stage", "deals", ["stage"])
    op.create_index("idx_deals_survey", "deals", ["survey_id"])
    op.create_index("idx_deals_verdict", "deals", ["verdict"])

    # ── deal_memos ───────────────────────────────────────────────────────────
    op.create_table("deal_memos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("deals.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("memo_type", sa.String(50), server_default="full"),
        sa.Column("sections", postgresql.JSONB(), nullable=False),
        sa.Column("recommendation", sa.String(20)),
        sa.Column("recommendation_text", sa.Text()),
        sa.Column("created_by", sa.String(100)),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("board_sessions.session_id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_memos_deal", "deal_memos", ["deal_id"])
    op.create_index("idx_memos_type", "deal_memos", ["memo_type"])

    # ── lls_projects ─────────────────────────────────────────────────────────
    op.create_table("lls_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("deals.id")),
        sa.Column("project_name", sa.String(200), nullable=False),
        sa.Column("survey_no", sa.String(100)),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("micro_markets.id")),
        sa.Column("milestones", postgresql.JSONB()),
        sa.Column("project_status", sa.String(50), server_default="planning"),
        sa.Column("lls_investment_rs", sa.DECIMAL(15, 2)),
        sa.Column("lls_equity_pct", sa.DECIMAL(5, 2)),
        sa.Column("partner_name", sa.String(200)),
        sa.Column("target_irr", sa.DECIMAL(5, 2)),
        sa.Column("actual_irr", sa.DECIMAL(5, 2)),
        sa.Column("start_date", sa.Date()),
        sa.Column("expected_completion", sa.Date()),
        sa.Column("actual_completion", sa.Date()),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_lls_market", "lls_projects", ["micro_market_id"])
    op.create_index("idx_lls_deal", "lls_projects", ["deal_id"])
    op.create_index("idx_lls_status", "lls_projects", ["project_status"])

    # ── agreements ───────────────────────────────────────────────────────────
    op.create_table("agreements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("deals.id")),
        sa.Column("agreement_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200)),
        sa.Column("parties", postgresql.JSONB(), nullable=False),
        sa.Column("key_terms", postgresql.JSONB()),
        sa.Column("signed_date", sa.Date()),
        sa.Column("effective_date", sa.Date()),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("document_url", sa.Text()),
        sa.Column("status", sa.String(50), server_default="draft"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_agreements_deal", "agreements", ["deal_id"])
    op.create_index("idx_agreements_type", "agreements", ["agreement_type"])
    op.create_index("idx_agreements_status", "agreements", ["status"])

    # ── compliance_log ───────────────────────────────────────────────────────
    op.create_table("compliance_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compliance_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("due_date", sa.Date()),
        sa.Column("completed_date", sa.Date()),
        sa.Column("authority", sa.String(100)),
        sa.Column("reference_no", sa.String(200)),
        sa.Column("notes", sa.Text()),
        sa.Column("assigned_to", sa.String(100)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_compliance_entity", "compliance_log", ["entity_type", "entity_id"])
    op.create_index("idx_compliance_status", "compliance_log", ["status"])
    op.create_index("idx_compliance_due", "compliance_log", ["due_date"])

    # ── opportunity_scores ───────────────────────────────────────────────────
    op.create_table("opportunity_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("survey_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("surveys.id")),
        sa.Column("survey_no", sa.String(100)),
        sa.Column("micro_market_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("micro_markets.id"), nullable=False),
        sa.Column("developer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("developers.id")),
        sa.Column("score", sa.DECIMAL(5, 4), nullable=False),
        sa.Column("irr_score", sa.DECIMAL(5, 4)),
        sa.Column("legal_score", sa.DECIMAL(5, 4)),
        sa.Column("timing_score", sa.DECIMAL(5, 4)),
        sa.Column("distress_score", sa.DECIMAL(5, 4)),
        sa.Column("exclusivity_score", sa.DECIMAL(5, 4)),
        sa.Column("components", postgresql.JSONB()),
        sa.Column("best_deal_type", sa.String(50)),
        sa.Column("estimated_jd_irr", sa.DECIMAL(5, 2)),
        sa.Column("legal_risk_level", sa.String(20)),
        sa.Column("next_action", sa.Text()),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("pruned_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("idx_opp_scores_market_score", "opportunity_scores", ["micro_market_id", sa.text("score DESC")])
    op.create_index("idx_opp_scores_survey", "opportunity_scores", ["survey_id"])
    op.create_index("idx_opp_scores_active", "opportunity_scores", ["is_active"])
    op.create_index("idx_opp_scores_expiry", "opportunity_scores", ["expiry_date"])

    # ── ingest_log ───────────────────────────────────────────────────────────
    op.create_table("ingest_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("plugin_id", sa.String(100), nullable=False),
        sa.Column("source_id", sa.String(100)),
        sa.Column("market", sa.String(100)),
        sa.Column("entity_type", sa.String(50)),
        sa.Column("entity_id", sa.String(200)),
        sa.Column("data", postgresql.JSONB()),
        sa.Column("raw_hash", sa.String(64)),
        sa.Column("confidence", sa.DECIMAL(3, 2), server_default="1.0"),
        sa.Column("validation_errors", postgresql.JSONB()),
        sa.Column("status", sa.String(20), server_default="success"),
        sa.Column("error_message", sa.Text()),
        sa.Column("scraped_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_ingest_plugin", "ingest_log", ["plugin_id"])
    op.create_index("idx_ingest_market", "ingest_log", ["market"])
    op.create_index("idx_ingest_entity", "ingest_log", ["entity_type", "entity_id"])
    op.create_index("idx_ingest_status", "ingest_log", ["status"])
    op.create_index("idx_ingest_created", "ingest_log", [sa.text("created_at DESC")])
    op.create_index("idx_ingest_hash", "ingest_log", ["raw_hash"])

    # ── T-709 composite/partial indexes on existing tables ───────────────────
    op.create_index("idx_rera_projects_distressed", "rera_projects", ["micro_market_id", "project_status", "possession_date"])
    op.create_index("idx_rera_projects_active_inv", "rera_projects", ["micro_market_id", "is_active"], postgresql_where=sa.text("is_active = TRUE"))
    op.create_index("idx_kaveri_reg_market_date", "kaveri_registrations", ["micro_market_id", sa.text("transaction_date DESC")])
    op.create_index("idx_igr_market_date_v2", "igr_transactions", ["micro_market_id", sa.text("registration_date DESC")])
    op.create_index("idx_agent_registry_spec_gin", "agent_registry", [sa.text("spec")], postgresql_using="gin")


def downgrade() -> None:
    # Drop T-709 indexes first
    for idx_name in ("idx_agent_registry_spec_gin", "idx_igr_market_date_v2", "idx_kaveri_reg_market_date",
                     "idx_rera_projects_active_inv", "idx_rera_projects_distressed"):
        op.drop_index(idx_name, table_name=None)

    # Drop ingest_log indexes
    for idx_name in ("idx_ingest_hash", "idx_ingest_created", "idx_ingest_status", "idx_ingest_entity",
                     "idx_ingest_market", "idx_ingest_plugin"):
        op.drop_index(idx_name, table_name="ingest_log")
    op.drop_table("ingest_log")

    # Drop opportunity_scores indexes
    for idx_name in ("idx_opp_scores_expiry", "idx_opp_scores_active", "idx_opp_scores_survey", "idx_opp_scores_market_score"):
        op.drop_index(idx_name, table_name="opportunity_scores")
    op.drop_table("opportunity_scores")

    # Drop compliance_log indexes
    for idx_name in ("idx_compliance_due", "idx_compliance_status", "idx_compliance_entity"):
        op.drop_index(idx_name, table_name="compliance_log")
    op.drop_table("compliance_log")

    # Drop agreements indexes
    for idx_name in ("idx_agreements_status", "idx_agreements_type", "idx_agreements_deal"):
        op.drop_index(idx_name, table_name="agreements")
    op.drop_table("agreements")

    # Drop lls_projects indexes
    for idx_name in ("idx_lls_status", "idx_lls_deal", "idx_lls_market"):
        op.drop_index(idx_name, table_name="lls_projects")
    op.drop_table("lls_projects")

    # Drop deal_memos indexes
    for idx_name in ("idx_memos_type", "idx_memos_deal"):
        op.drop_index(idx_name, table_name="deal_memos")
    op.drop_table("deal_memos")

    # Drop deals indexes
    for idx_name in ("idx_deals_verdict", "idx_deals_survey", "idx_deals_stage", "idx_deals_market"):
        op.drop_index(idx_name, table_name="deals")
    op.drop_table("deals")

    # Drop demand_signals indexes
    op.drop_index("idx_demand_market", table_name="demand_signals")
    op.drop_table("demand_signals")

    # Drop developer_health indexes
    op.drop_index("idx_dev_health_score", table_name="developer_health")
    op.drop_table("developer_health")

    # Drop distressed_opps indexes
    for idx_name in ("idx_distressed_alert", "idx_distressed_market", "idx_distressed_score", "idx_distressed_dev"):
        op.drop_index(idx_name, table_name="distressed_opps")
    op.drop_table("distressed_opps")

    # Drop litigations indexes
    for idx_name in ("idx_litigations_status", "idx_litigations_market", "idx_litigations_survey_no", "idx_litigations_survey"):
        op.drop_index(idx_name, table_name="litigations")
    op.drop_table("litigations")

    # Drop khata_records indexes
    for idx_name in ("idx_khata_type", "idx_khata_market", "idx_khata_survey"):
        op.drop_index(idx_name, table_name="khata_records")
    op.drop_table("khata_records")

    # Drop rtc_records indexes
    for idx_name in ("idx_rtc_market", "idx_rtc_survey_no", "idx_rtc_survey"):
        op.drop_index(idx_name, table_name="rtc_records")
    op.drop_table("rtc_records")

    # Drop surveys indexes
    for idx_name in ("idx_surveys_parent", "idx_surveys_geom", "idx_surveys_survey_no", "idx_surveys_market"):
        op.drop_index(idx_name, table_name="surveys")
    op.drop_table("surveys")
