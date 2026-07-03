"""
T-1526–T-1529: Cross-Cutting Data Flow tests (GATE-168 prep).

Verifies that real component chains produce correct results when intermediate
DB layers are mocked — catching integration drift that individual gate tests
cannot see.

Task tree
---------
T-1526  test_deed_to_score_chain             — ParcelGraph -> score_deal flow
        test_deed_to_score_chain_no_shared_buyer  (edge: different buyers)
        test_deed_to_score_chain_empty_rows        (edge: empty DB)
T-1527  TestCalibrationHealth class          — Ops calibration endpoint (4 scenarios)
T-1528  test_deal_score_log_chain            — score -> DB insert -> history
T-1529  TestDigestQuality class              — validate_digest coverage (4 scenarios)
"""

import math
import os
from datetime import datetime, timezone, date
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")
os.environ.setdefault("DASHBOARD_API_KEY_ADMIN", "test-admin-key")

pytestmark = pytest.mark.unit




# ═══════════════════════════════════════════════════════════════════════════
# T-1526: Deed -> Score chain
# ═══════════════════════════════════════════════════════════════════════════


def test_deed_to_score_chain():
    """T-1526: ParcelGraph builds edges from mock deed data with shared buyer,
    then AssemblyDetector real path through score_deal produces non-fallback score.

    Two-part test:
      1. Mock ``registered_transactions`` rows with same buyer -> edges with
         ``shared_buyer=True``.
      2. Mock ``assembly_detector.get_engine()`` so ``detect_clusters()``
         forms a real cluster from 3 deeds -> ``assembly_score != 0.5``
         (not the fallback).
    """
    from tests.conftest import _make_engine
    from utils.parcel_graph import ParcelGraph
    from utils.deal_scorer import score_deal

    # -- Part 1: ParcelGraph with shared buyer --
    mock_conn1 = MagicMock()
    mock_conn1.execute.return_value.fetchall.return_value = [
        MagicMock(survey_no="120A", buyer_name_raw="Prestige", reg_date=date(2025, 1, 1)),
        MagicMock(survey_no="120B", buyer_name_raw="Prestige", reg_date=date(2025, 1, 20)),
    ]

    with patch("utils.parcel_graph.get_engine", return_value=_make_engine(mock_conn1)):
        result = ParcelGraph().build("Yelahanka", "Doddajala")

    assert len(result["edges"]) > 0, (
        "T-1526 p1: expected >=1 edge with shared buyer; got 0"
    )
    assert any(e.get("shared_buyer") for e in result["edges"]), (
        "T-1526 p1: expected at least one edge with shared_buyer=True"
    )
    # Verify structure
    assert "nodes" in result
    assert "hotspot_score" in result
    assert result["hotspot_score"] > 0, "hotspot_score should be >0 with edges"

    # -- Part 2: AssemblyDetector real path through score_deal --
    mock_conn2 = MagicMock()
    mock_conn2.execute.return_value.fetchall.return_value = [
        MagicMock(village="Doddajala", hobli="Yelahanka Hobli",
                  buyer_name_raw="Prestige Group", survey_no="120A",
                  reg_date=date(2025, 1, 1), extent_sqft=12000.0,
                  consideration_inr=50000000),
        MagicMock(village="Doddajala", hobli="Yelahanka Hobli",
                  buyer_name_raw="Prestige Group", survey_no="121",
                  reg_date=date(2025, 1, 15), extent_sqft=15000.0,
                  consideration_inr=60000000),
        MagicMock(village="Doddajala", hobli="Yelahanka Hobli",
                  buyer_name_raw="Prestige Group", survey_no="122",
                  reg_date=date(2025, 2, 1), extent_sqft=10000.0,
                  consideration_inr=40000000),
    ]

    with (
        patch("utils.assembly_detector.get_engine", return_value=_make_engine(mock_conn2)),
        patch("utils.assembly_detector.AssemblyDetector._upsert_clusters"),
        patch("utils.deal_scorer._compute_corridor_score", return_value=(0.5, 1)),
        patch("utils.deal_scorer._compute_strr_score", return_value=(0.5, "unknown")),
        patch("utils.deal_scorer._compute_irr_score", return_value=(0.5, None, None)),
        patch("utils.deal_scorer._compute_kill_criteria_score", return_value=(0.5, "at_risk")),
    ):
        deal_result = score_deal("Yelahanka", 5.0, 1.5)

    assert deal_result["signals"]["assembly"] != 0.5, (
        f"T-1526 p2: expected assembly_score != 0.5 (real cluster), "
        f"got {deal_result['signals']['assembly']}"
    )
    # Fallback_count should be 0.5 from IRR (avg_psf=None) only
    assert deal_result["metadata"]["fallback_count"] == 0.5, (
        f"T-1526 p2: expected fallback_count=0.5 (only IRR), "
        f"got {deal_result['metadata']['fallback_count']}"
    )
    assert deal_result["metadata"]["assembly_clusters"] > 0, (
        "T-1526 p2: expected assembly_clusters > 0"
    )


def test_deed_to_score_chain_no_shared_buyer():
    """T-1526 edge: different buyer names produce edges but NO shared_buyer."""
    from tests.conftest import _make_engine
    from utils.parcel_graph import ParcelGraph

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        MagicMock(survey_no="10A", buyer_name_raw="Brigade", reg_date=date(2025, 3, 1)),
        MagicMock(survey_no="10B", buyer_name_raw="Prestige", reg_date=date(2025, 3, 15)),
    ]

    with patch("utils.parcel_graph.get_engine", return_value=_make_engine(mock_conn)):
        result = ParcelGraph().build("Yelahanka", "Doddajala")

    # Different buyers -> numeric adjacency may still connect 10A/10B
    assert "edges" in result
    # But NO shared_buyer edge (buyer names differ)
    assert not any(e.get("shared_buyer") for e in result["edges"]), (
        "T-1526 edge: different buyers should not produce shared_buyer edges"
    )


def test_deed_to_score_chain_empty_rows():
    """T-1526 edge: empty DB result returns empty graph without raising."""
    from tests.conftest import _make_engine
    from utils.parcel_graph import ParcelGraph

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []

    with patch("utils.parcel_graph.get_engine", return_value=_make_engine(mock_conn)):
        result = ParcelGraph().build("Yelahanka", "Doddajala")

    assert result["edges"] == []
    assert result["nodes"] == []
    assert result["hotspot_score"] == 0.0
    assert result["market"] == "Yelahanka"
    assert result["village"] == "Doddajala"


# ═══════════════════════════════════════════════════════════════════════════
# T-1527: Calibration -> overall_health chain
# ═══════════════════════════════════════════════════════════════════════════


class TestCalibrationHealth:
    """T-1527: ``GET /api/v1/ops/calibration`` ``overall_health`` reflects
    ``calibration_snapshots`` data across 4 scenarios."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, monkeypatch):
        """Ensure API keys are set before app import."""
        monkeypatch.setitem(os.environ, "DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
        monkeypatch.setitem(os.environ, "DASHBOARD_API_KEY", "test-key")
        monkeypatch.setitem(os.environ, "DASHBOARD_API_KEY_READ", "test-read-key")
        monkeypatch.setitem(os.environ, "DASHBOARD_API_KEY_ADMIN", "test-admin-key")

    def _fetch_overall_health(self, mock_return_value, dashboard_client):
        """Helper: patch ``_get_sa_engine``, GET /calibration, return ``overall_health``."""
        from tests.conftest import _make_engine

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = mock_return_value

        with patch("dashboard.routers.ops._get_sa_engine", return_value=_make_engine(mock_conn)):
            resp = dashboard_client.get(
                "/api/v1/ops/calibration",
                headers={"X-API-Key": "test-key"},
            )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        return resp.json()

    def test_calibration_health_degrading(self, dashboard_client):
        """All 3 markets degrading -> ``overall_health == 'degrading'``."""
        now = datetime.now(timezone.utc)
        health = self._fetch_overall_health(
            (25, "degrading", 5, now), dashboard_client,
        )
        assert health["overall_health"] == "degrading", (
            f"expected degrading, got {health['overall_health']}"
        )

    def test_calibration_health_good(self, dashboard_client):
        """All 3 markets low+stable -> ``overall_health == 'good'``."""
        now = datetime.now(timezone.utc)
        health = self._fetch_overall_health(
            (10, "stable", 2, now), dashboard_client,
        )
        assert health["overall_health"] == "good", (
            f"expected good, got {health['overall_health']}"
        )

    def test_calibration_health_unknown(self, dashboard_client):
        """No data in ``calibration_snapshots`` -> ``overall_health == 'unknown'``."""
        health = self._fetch_overall_health(None, dashboard_client)
        assert health["overall_health"] == "unknown", (
            f"expected unknown, got {health['overall_health']}"
        )

    def test_calibration_health_mixed(self, dashboard_client):
        """Mixed degrading + good data -> health == 'degrading' (any degrading wins)."""
        from tests.conftest import _make_engine
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        mock_conn = MagicMock()

        call_results = [
            (25, "degrading", 5, now),   # Yelahanka
            (10, "stable", 2, now),      # Devanahalli
            (8, "stable", 1, now),       # Hebbal
        ]
        call_idx = [0]

        def side_effect(*_a, **_kw):
            idx = call_idx[0]
            call_idx[0] += 1
            mr = MagicMock()
            mr.fetchone.return_value = call_results[idx % len(call_results)]
            return mr

        mock_conn.execute.side_effect = side_effect

        with patch("dashboard.routers.ops._get_sa_engine", return_value=_make_engine(mock_conn)):
            resp = dashboard_client.get(
                "/api/v1/ops/calibration",
                headers={"X-API-Key": "test-key"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_health"] == "degrading", (
            f"expected degrading (any_degrading=True), got {data['overall_health']}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# T-1528: Deal score log chain
# ═══════════════════════════════════════════════════════════════════════════


def test_deal_score_log_chain():
    """T-1528: score_deal -> endpoint INSERT into ``deal_score_log`` -> history.

    Steps:
      1. Call ``score_deal()`` with deterministic sub-scorer mocks -> result dict.
      2. Call the endpoint, capture ``_get_sa_engine().begin().__enter__().execute()``
         calls, verify the INSERT SQL targets ``deal_score_log`` and params match
         the expected ``overall_score``.
      3. Mock a ``deal_score_log`` SELECT and verify the history endpoint returns
         a list with the expected entry.
    """
    from tests.conftest import _make_engine
    from utils.deal_scorer import score_deal

    # -- Step 1: score_deal with deterministic sub-scorer values --
    from contextlib import ExitStack

    sub_scorer_patches = [
        patch("utils.deal_scorer._compute_assembly_score", return_value=(0.7, 3)),
        patch("utils.deal_scorer._compute_corridor_score", return_value=(0.8, 2)),
        patch("utils.deal_scorer._compute_strr_score", return_value=(1.0, "STRONG")),
        patch("utils.deal_scorer._compute_irr_score", return_value=(0.7, 19.5, 8500.0)),
        patch("utils.deal_scorer._compute_kill_criteria_score", return_value=(1.0, "on_track")),
    ]

    with ExitStack() as stack:
        for p in sub_scorer_patches:
            stack.enter_context(p)
        deal_result = score_deal("Yelahanka", 5.0, 1.5)

    assert deal_result["verdict"] in {"GO", "CAUTIOUS", "NO-GO"}
    expected_overall = deal_result["overall_score"]

    # -- Step 2: Call endpoint, capture INSERT SQL + params --
    executed_sql_texts: list[str] = []
    executed_params_list: list[dict] = []

    def capture_execute(*args, **_kwargs):
        if args:
            sql_text = str(args[0])
            executed_sql_texts.append(sql_text)
            if len(args) > 1 and isinstance(args[1], dict):
                executed_params_list.append(args[1])
        return MagicMock()

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = capture_execute
    mock_engine = _make_engine(mock_conn)

    with ExitStack() as stack:
        for p in sub_scorer_patches:
            stack.enter_context(p)
        stack.enter_context(patch("dashboard.routers.data._get_sa_engine", return_value=mock_engine))
        stack.enter_context(patch("dashboard.routers.data._DEAL_SCORE_CACHE", {}))
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/intel/deal-score?market=Yelahanka&land_cost_cr=5.0&area_acres=1.5",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200, (
        f"T-1528 step2: endpoint returned {resp.status_code}: {resp.text[:200]}"
    )

    insert_found = any("deal_score_log" in sql for sql in executed_sql_texts)
    assert insert_found, (
        "T-1528 step2: no INSERT INTO deal_score_log found in captured SQL calls"
    )

    params_match = False
    for p in executed_params_list:
        if p.get("market") == "Yelahanka" and "overall_score" in p:
            assert math.isclose(p["overall_score"], expected_overall, rel_tol=1e-6), (
                f"T-1528 step2: overall_score mismatch in INSERT params: "
                f"{p['overall_score']} != {expected_overall}"
            )
            params_match = True
            break
    assert params_match, (
        "T-1528 step2: no INSERT params found with "
        "market=Yelahanka and overall_score"
    )

    # -- Step 3: History endpoint --
    mock_conn2 = MagicMock()
    mock_conn2.execute.return_value.fetchall.return_value = [
        (expected_overall, "GO", 0.85, 0.7, 0.8, 1.0, 0.7, 1.0,
         "Top factors", datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc),
         5.0, 1.5),
    ]
    mock_engine2 = MagicMock()
    mock_engine2.connect.return_value.__enter__.return_value = mock_conn2

    with patch("dashboard.routers.data._get_sa_engine", return_value=mock_engine2):
        resp = client.get(
            "/api/v1/intel/deal-score/history?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200, (
        f"T-1528 step3: history endpoint returned {resp.status_code}"
    )
    data = resp.json()
    assert "history" in data
    assert isinstance(data["history"], list)
    assert len(data["history"]) >= 1, "expected at least 1 history entry"
    assert data["history"][0]["verdict"] == "GO"
    assert data["count"] >= 1
    assert "generated_at" in data

    # Verify the score round-trips
    assert math.isclose(
        data["history"][0]["overall_score"], expected_overall, rel_tol=1e-6
    ), "history overall_score does not match computed score"





# ═══════════════════════════════════════════════════════════════════════════
# T-1529: Digest quality chain
# ═══════════════════════════════════════════════════════════════════════════


class TestDigestQuality:
    """T-1529: ``validate_digest`` coverage flow — 4 scenarios."""

    _ALL_KEYS = {"market_coverage", "freshness_ok", "signal_count",
                 "avg_confidence_pct", "verdict"}

    def _assert_all_keys_present(self, result: dict):
        for key in self._ALL_KEYS:
            assert key in result, f"missing key {key} in validate_digest result"

    def test_digest_quality_coverage_true(self):
        """Agent runs row exists -> ``market_coverage=True``."""
        from tests.conftest import _make_engine, _make_execute_side_effect
        from utils.digest_validator import validate_digest

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = _make_execute_side_effect([
            (1,),     # agent_runs row exists
            (10,),    # 10 rera_projects updated
            (3, 0.8), # 3 assembly_signals with avg confidence 0.8
        ])

        with patch("utils.digest_validator.get_engine",
                   return_value=_make_engine(mock_conn)):
            result = validate_digest("Yelahanka")

        self._assert_all_keys_present(result)
        assert result["market_coverage"] is True
        assert result["freshness_ok"] is True
        assert result["signal_count"] >= 1
        assert result["avg_confidence_pct"] > 0
        assert result["verdict"] == "PASS", (
            f"expected PASS with all checks OK, got {result['verdict']}"
        )

    def test_digest_quality_empty_db_fail(self):
        """No rows anywhere -> ``market_coverage=False``, ``verdict=FAIL``."""
        from tests.conftest import _make_engine
        from utils.digest_validator import validate_digest

        mock_r = MagicMock()
        mock_r.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_r

        with patch("utils.digest_validator.get_engine",
                   return_value=_make_engine(mock_conn)):
            result = validate_digest("Yelahanka")

        self._assert_all_keys_present(result)
        assert result["market_coverage"] is False
        assert result["freshness_ok"] is False
        assert result["signal_count"] == 0
        assert result["avg_confidence_pct"] == 0.0
        assert result["verdict"] == "FAIL"

    def test_digest_quality_empty_market_fail(self):
        """Empty market string returns FAIL without DB call."""
        from utils.digest_validator import validate_digest

        result = validate_digest("")
        self._assert_all_keys_present(result)
        assert result["market_coverage"] is False
        assert result["verdict"] == "FAIL"

    def test_digest_quality_none_market_fail(self):
        """None market returns FAIL without DB call."""
        from utils.digest_validator import validate_digest

        result = validate_digest(None)
        self._assert_all_keys_present(result)
        assert result["market_coverage"] is False
        assert result["verdict"] == "FAIL"
