"""T-1416: Assembly drilldown endpoints (resolve + obsidian-export)."""
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestAssemblyResolve:
    def test_resolve_endpoint_registered(self):
        from dashboard.routers.data import router
        routes = [(r.path, list(r.methods)) for r in router.routes]
        assert any(
            "/intel/assembly/{signal_id}/resolve" in p and "POST" in m
            for p, m in routes
        )

    def test_resolve_sql_executes_correct_update(self):
        from dashboard.routers.data import assembly_resolve
        from fastapi import Request
        mock_req = MagicMock(spec=Request)
        mock_req.state.role = "admin"
        with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
            mock_conn = mock_eng.return_value.begin.return_value.__enter__.return_value
            mock_conn.execute.return_value.rowcount = 1
            import asyncio
            coro = assembly_resolve("550e8400-e29b-41d4-a716-446655440000", mock_req)
            asyncio.run(coro)
            sql_obj = mock_conn.execute.call_args[0][0]
            assert "resolved_at" in str(sql_obj)
            assert ":sid" in str(sql_obj)

    def test_resolve_returns_404_on_missing_signal(self):
        from dashboard.routers.data import assembly_resolve
        from fastapi import Request
        mock_req = MagicMock(spec=Request)
        mock_req.state.role = "admin"
        with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
            mock_conn = mock_eng.return_value.begin.return_value.__enter__.return_value
            mock_conn.execute.return_value.rowcount = 0
            import asyncio
            coro = assembly_resolve("550e8400-e29b-41d4-a716-446655440001", mock_req)
            resp = asyncio.run(coro)
            assert resp.status_code == 404

    def test_resolve_invalid_uuid_returns_400(self):
        from dashboard.routers.data import assembly_resolve
        from fastapi import Request
        mock_req = MagicMock(spec=Request)
        mock_req.state.role = "admin"
        with patch("dashboard.routers.data._get_sa_engine"):
            import asyncio
            coro = assembly_resolve("not-a-uuid", mock_req)
            resp = asyncio.run(coro)
            assert resp.status_code == 400

    def test_obsidian_export_path_registered(self):
        from dashboard.routers.data import router
        routes = [(r.path, list(r.methods)) for r in router.routes]
        assert any(
            "/intel/assembly/{signal_id}/obsidian-export" in p
            for p, m in routes
        )

    def test_obsidian_export_in_read_only_paths(self):
        from dashboard.state import _READ_ONLY_PATHS
        assert any("obsidian-export" in p for p in _READ_ONLY_PATHS)
