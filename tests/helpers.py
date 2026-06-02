"""
Shared test helpers for Sprint 39 + future unit tests.
"""
from unittest.mock import MagicMock


def make_mock_engine(rows_data: list[tuple], row_attr_names: list[str] | None = None):
    """Create a mock SQLAlchemy engine returning rows with named attributes.

    Default attr names: developer_name, market, total_projects, active_projects,
    delayed_projects, avg_delay_months, incomplete_ratio, complaint_count, distress_score.
    """
    if row_attr_names is None:
        row_attr_names = ["developer_name", "market", "total_projects",
                          "active_projects", "delayed_projects", "avg_delay_months",
                          "incomplete_ratio", "complaint_count", "distress_score"]
    mock_row = MagicMock()
    mock_row.fetchall.return_value = [
        MagicMock(**{name: r[i] for i, name in enumerate(row_attr_names)})
        for r in rows_data
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value.execute.return_value = mock_row
    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn
    return mock_engine
