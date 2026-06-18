"""T-1287 — mypy blind spots doc exists."""
import pytest
from pathlib import Path
pytestmark = pytest.mark.unit

def test_mypy_blind_spots_doc_exists():
    doc = Path("docs/solutions/best-practices/mypy_blind_spots.md")
    assert doc.exists(), "mypy blind spots doc not found"
    content = doc.read_text()
    assert "# mypy Blind Spots Audit" in content
    assert "psycopg2" in content
    assert "chromadb" in content
    assert "yaml" in content
    assert "HIGH" in content
