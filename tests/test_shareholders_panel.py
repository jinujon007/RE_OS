"""Tests for /shareholders dashboard panel."""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


class TestShareholdersPanel:
    def test_shareholders_route_returns_template(self):
        """Verify /shareholders route renders the template."""
        with patch("dashboard.app_fastapi.templates.TemplateResponse") as mock_render:
            mock_render.return_value = "rendered"
            from dashboard.app_fastapi import shareholders_panel

            class MockRequest:
                url = type("url", (), {"path": "/shareholders"})()

            result = shareholders_panel(MockRequest())
            assert result is not None

    def test_template_file_exists(self):
        from pathlib import Path

        path = Path("dashboard/templates/shareholders.html")
        assert path.exists(), f"Template not found: {path}"
        content = path.read_text(encoding="utf-8")
        assert "Shareholder Room" in content
