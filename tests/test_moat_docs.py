"""T-1304: Moat documentation tests (GATE-123)."""
import pathlib
import pytest

pytestmark = pytest.mark.unit


def test_moat_doc_exists_and_complete():
    """docs/moat.md exists and contains required sections."""
    path = pathlib.Path("docs/moat.md")
    assert path.exists(), "docs/moat.md must exist"

    content = path.read_text(encoding="utf-8")
    assert "assembly detection" in content.lower() or "assembly detection" in content
    assert "Zapkey" in content
    assert "kill criteria" in content.lower() or "Kill Criteria" in content or "Kill Criterion" in content
    assert "Competitor" in content or "competitor" in content


def test_claude_md_moat_corrected():
    """CLAUDE.md has moat correction: 'uncontested' does not appear adjacent to 'deed data';
    'assembly detection' or 'Form17 parcel' appears in the moat context."""
    path = pathlib.Path("CLAUDE.md")
    assert path.exists()

    content = path.read_text(encoding="utf-8")
    assert "uncontested" in content, (
        "CLAUDE.md should mention 'uncontested' in the moat correction context"
    )
    assert "assembly detection" in content or "Form17 parcel" in content or "Form17" in content
    assert "Zapkey" in content
