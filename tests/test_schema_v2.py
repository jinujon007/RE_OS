"""
RE_OS v2 — Schema Tests (T-658)
>=15 tests: table existence, FK validity, view returns, seed data.
"""
import pytest
pytestmark = pytest.mark.unit

from sqlalchemy import text, inspect
from utils.db import get_engine


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_tables(conn):
    inspector = inspect(conn)
    return set(inspector.get_table_names())


def _get_views(conn):
    rows = conn.execute(text("""
        SELECT table_name FROM information_schema.views
        WHERE table_schema = 'public'
    """)).fetchall()
    return {r[0] for r in rows}


def _get_columns(conn, table):
    inspector = inspect(conn)
    return {c["name"] for c in inspector.get_columns(table)}


@pytest.fixture(scope="function")
def tx_conn():
    """Transactional connection — all DML rolled back after test."""
    engine = get_engine()
    conn = engine.connect()
    trans = conn.begin()
    try:
        yield conn
    finally:
        trans.rollback()
        conn.close()


@pytest.fixture(scope="module")
def conn():
    engine = get_engine()
    with engine.connect() as c:
        yield c


# ── Table existence tests ─────────────────────────────────────────────────────

class TestV2TablesExist:
    def test_all_v1_tables_present(self, conn):
        tables = _get_tables(conn)
        for t in ("micro_markets", "developers", "rera_projects", "project_snapshots",
                  "listings", "kaveri_registrations", "igr_transactions",
                  "guidance_values", "regulatory_zones", "overlay_constraints",
                  "infrastructure_pipeline", "osm_edges", "market_snapshots",
                  "news_articles", "agent_runs", "agent_memories", "board_sessions",
                  "tasks", "alerts", "agent_registry"):
            assert t in tables, f"V1 table '{t}' is missing"

    def test_all_v2_tables_present(self, conn):
        tables = _get_tables(conn)
        for t in ("surveys", "rtc_records", "khata_records", "litigations",
                  "distressed_opps", "developer_health", "demand_signals",
                  "deals", "deal_memos", "lls_projects", "agreements",
                  "compliance_log", "opportunity_scores", "ingest_log"):
            assert t in tables, f"V2 table '{t}' is missing"

    def test_surveys_has_expected_columns(self, conn):
        cols = _get_columns(conn, "surveys")
        for c in ("survey_no", "micro_market_id", "village", "taluk",
                  "total_area_acres", "land_type", "ownership_type",
                  "dc_conversion_status", "khata_no", "encumbrance_clear"):
            assert c in cols, f"surveys missing column '{c}'"

    def test_deals_has_expected_columns(self, conn):
        cols = _get_columns(conn, "deals")
        for c in ("deal_name", "deal_type", "stage", "survey_id",
                  "area_acres", "ask_psf", "irr_base", "verdict", "deal_lead"):
            assert c in cols, f"deals missing column '{c}'"

    def test_ingest_log_has_expected_columns(self, conn):
        cols = _get_columns(conn, "ingest_log")
        for c in ("plugin_id", "market", "entity_type", "status",
                  "raw_hash", "confidence", "validation_errors"):
            assert c in cols, f"ingest_log missing column '{c}'"


# ── FK constraint tests ──────────────────────────────────────────────────────

class TestFKConstraints:
    def test_surveys_fk_to_micro_markets(self, conn):
        result = conn.execute(text("""
            SELECT 1 FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu USING (constraint_name)
            WHERE tc.table_name = 'surveys'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'micro_market_id'
        """)).fetchone()
        assert result is not None, "surveys missing FK to micro_markets"

    def test_deals_fk_to_surveys(self, conn):
        result = conn.execute(text("""
            SELECT 1 FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu USING (constraint_name)
            WHERE tc.table_name = 'deals'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'survey_id'
        """)).fetchone()
        assert result is not None, "deals missing FK to surveys"

    def test_opportunity_scores_fk_to_surveys(self, conn):
        result = conn.execute(text("""
            SELECT 1 FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu USING (constraint_name)
            WHERE tc.table_name = 'opportunity_scores'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'survey_id'
        """)).fetchone()
        assert result is not None, "opportunity_scores missing FK to surveys"


# ── View tests ───────────────────────────────────────────────────────────────

class TestV2Views:
    def test_v_opportunity_queue_exists(self, conn):
        views = _get_views(conn)
        assert "v_opportunity_queue" in views, "v_opportunity_queue view missing"

    def test_v_developer_health_exists(self, conn):
        views = _get_views(conn)
        assert "v_developer_health" in views, "v_developer_health view missing"

    def test_v_market_pulse_exists(self, conn):
        views = _get_views(conn)
        assert "v_market_pulse" in views, "v_market_pulse view missing"

    def test_v_survey_full_picture_exists(self, conn):
        views = _get_views(conn)
        assert "v_survey_full_picture" in views, "v_survey_full_picture view missing"

    def test_v_deal_pipeline_kanban_exists(self, conn):
        views = _get_views(conn)
        assert "v_deal_pipeline_kanban" in views, "v_deal_pipeline_kanban view missing"

    def test_v_data_freshness_exists(self, conn):
        views = _get_views(conn)
        assert "v_data_freshness" in views, "v_data_freshness view missing"

    def test_v_opportunity_queue_returns_without_error(self, conn):
        rows = conn.execute(text("SELECT COUNT(*) FROM v_opportunity_queue")).fetchone()
        assert rows is not None, "v_opportunity_queue query failed"

    def test_v_data_freshness_returns_without_error(self, conn):
        rows = conn.execute(text("SELECT COUNT(*) FROM v_data_freshness")).fetchone()
        assert rows is not None, "v_data_freshness query failed"


# ── DML operability tests (transactional — rollback after test) ───────────────

class TestDML:
    def test_ingest_log_insertable(self, tx_conn):
        with tx_conn.begin():
            conn.execute(text("""
                INSERT INTO ingest_log (plugin_id, market, status)
                VALUES (:p, :m, :s)
            """), {"p": "test_plugin", "m": "test_market", "s": "success"})
            row = conn.execute(text("""
                SELECT COUNT(*) FROM ingest_log WHERE plugin_id = 'test_plugin'
            """)).fetchone()
            assert row[0] >= 1, "ingest_log insert failed"

    def test_ingest_log_idempotent_reinsert(self, tx_conn):
        with tx_conn.begin():
            conn.execute(text("""
                INSERT INTO ingest_log (plugin_id, market, entity_type, status)
                VALUES (:p, :m, :e, :s)
            """), {"p": "test_dedup", "m": "test", "e": "test_entity", "s": "success"})
            conn.execute(text("""
                INSERT INTO ingest_log (plugin_id, market, entity_type, status)
                VALUES (:p, :m, :e, :s)
            """), {"p": "test_dedup", "m": "test", "e": "test_entity", "s": "success"})
            row = conn.execute(text("""
                SELECT COUNT(*) FROM ingest_log WHERE plugin_id = 'test_dedup'
            """)).fetchone()
            assert row[0] == 2, "ingest_log should allow multiple similar rows (no unique constraint)"

    def test_opportunity_scores_insertable(self, tx_conn):
        with tx_conn.begin():
            row = conn.execute(text("""
                INSERT INTO opportunity_scores (survey_no, micro_market_id, score)
                SELECT 'TEST-SURVEY', id, 0.7500
                FROM micro_markets
                WHERE slug = 'yelahanka'
                RETURNING id
            """)).fetchone()
            assert row is not None, "opportunity_scores insert failed"

    def test_deals_insertable(self, tx_conn):
        with tx_conn.begin():
            row = tx_conn.execute(text("""
                INSERT INTO deals (deal_name, deal_type, stage)
                VALUES (:n, :t, :s)
                RETURNING id
            """), {"n": "Test Deal", "t": "jd", "s": "evaluating"}).fetchone()
            assert row is not None, "deals insert failed"

    def test_surveys_insertable(self, tx_conn):
        with tx_conn.begin():
            row = tx_conn.execute(text("""
                INSERT INTO surveys (survey_no, micro_market_id)
                SELECT 'TEST-SVY-001', id
                FROM micro_markets
                WHERE slug = 'devanahalli'
                RETURNING id
            """)).fetchone()
            assert row is not None, "surveys insert failed"


# ── Seed data validation tests ────────────────────────────────────────────────

class TestSeedData:
    def test_aiz_zones_seeded(self, conn):
        count = conn.execute(text("""
            SELECT COUNT(*) FROM regulatory_zones WHERE zone_type = 'AIZ'
        """)).fetchone()[0]
        assert count >= 4, f"Expected >=4 AIZ zones, got {count}"

    def test_developer_aliases_seeded(self, conn):
        count = conn.execute(text("""
            SELECT COUNT(*) FROM developer_aliases
        """)).fetchone()[0]
        assert count >= 25, f"Expected >=25 developer aliases, got {count}"

    def test_soil_zones_seeded(self, conn):
        count = conn.execute(text("""
            SELECT COUNT(*) FROM seed_soil_zones
        """)).fetchone()[0]
        assert count >= 10, f"Expected >=10 soil zones, got {count}"

    def test_parking_norms_seeded(self, conn):
        count = conn.execute(text("""
            SELECT COUNT(*) FROM seed_parking_norms
        """)).fetchone()[0]
        assert count >= 10, f"Expected >=10 parking norms, got {count}"

    def test_micro_markets_seeded(self, conn):
        count = conn.execute(text("""
            SELECT COUNT(*) FROM micro_markets WHERE priority = 1
        """)).fetchone()[0]
        assert count >= 6, f"Expected >=6 active micro-markets, got {count}"


# ── Negative / edge-case tests ────────────────────────────────────────────────

class TestNegativeCases:
    def test_unknown_table_raises(self, conn):
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        assert "nonexistent_table_v2" not in tables

    def test_opportunity_score_overflow_prevented(self, tx_conn):
        with tx_conn.begin():
            from sqlalchemy import exc
            with pytest.raises((exc.DataError, exc.IntegrityError)):
                tx_conn.execute(text("""
                    INSERT INTO opportunity_scores (survey_no, micro_market_id, score, irr_score)
                    SELECT 'OVERFLOW-TEST', id, 1.5, -0.1
                    FROM micro_markets WHERE slug = 'yelahanka'
                """))


# ── T-709 index existence tests ──────────────────────────────────────────────

class TestIndexSpec:
    def test_idx_rera_projects_distressed_exists(self, conn):
        indexes = conn.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'rera_projects' AND indexname = 'idx_rera_projects_distressed'
        """)).fetchone()
        assert indexes is not None, "T-709 Path 1 index missing"

    def test_idx_kaveri_reg_market_date_exists(self, conn):
        indexes = conn.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'kaveri_registrations' AND indexname = 'idx_kaveri_reg_market_date'
        """)).fetchone()
        assert indexes is not None, "T-709 Path 3 index missing"

    def test_idx_agent_registry_spec_gin_exists(self, conn):
        indexes = conn.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'agent_registry' AND indexname = 'idx_agent_registry_spec_gin'
        """)).fetchone()
        assert indexes is not None, "T-709 Path 6 GIN index missing"
