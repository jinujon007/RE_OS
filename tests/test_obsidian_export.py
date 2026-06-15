import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestObsidianExport:
    def test_obsidian_export_skips_gracefully_when_path_missing(self):
        from utils.obsidian_export import ObsidianExport

        with patch("utils.obsidian_export.os.path.isdir", return_value=False):
            result = ObsidianExport.write_weekly([], "2026-06-08")
            assert result == ""

    def test_obsidian_export_writes_correct_frontmatter(self):
        from utils.obsidian_export import ObsidianExport
        from utils.weekly_digest import WeeklyDigestResult

        result_obj = WeeklyDigestResult(
            market="Yelahanka",
            psf_delta_pct=5.25,
            psf_direction="up",
            new_rera_count=3,
            competitor_launches=[],
            distressed_developers=[],
            top_opportunity=None,
        )
        with patch("utils.obsidian_export.os.path.isdir", return_value=True):
            mock_open = MagicMock()
            with patch("builtins.open", mock_open):
                with patch(
                    "utils.obsidian_export.os.path.join", return_value="/fake/path.md"
                ):
                    result = ObsidianExport.write_weekly([result_obj], "2026-06-08")
                    assert result == "/fake/path.md"
                    handle = mock_open.return_value.__enter__.return_value
                    written = "".join(c[0][0] for c in handle.write.call_args_list)
                    assert "type: wiki" in written
                    assert "date: 2026-06-08" in written
                    assert "ai_generated: true" in written
                    assert "Weekly Market Digest" in written

    def test_obsidian_export_rejects_wrong_type(self):
        from utils.obsidian_export import ObsidianExport
        from utils.monthly_digest import MonthlyDigestResult

        wrong_type = MonthlyDigestResult(market="Yelahanka")
        with patch("utils.obsidian_export.os.path.isdir", return_value=True):
            result = ObsidianExport.write_weekly([wrong_type], "2026-06-08")
            assert result == ""

    def test_obsidian_export_skips_empty_results(self):
        from utils.obsidian_export import ObsidianExport

        with patch("utils.obsidian_export.os.path.isdir", return_value=True):
            result = ObsidianExport.write_monthly([], "2026-06-08")
            assert result == ""
