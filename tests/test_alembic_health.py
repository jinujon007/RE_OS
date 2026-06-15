"""Alembic health checks: single head, no branching.

Parses migration files directly to avoid importing migration modules
(which depend on geoalchemy2 and other heavy deps).
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

MIGRATIONS_DIR = Path(__file__).parents[1] / "alembic" / "versions"

_REV_RE = re.compile(
    r"""^revision(?:\s*:\s*str)?\s*=\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def _parse_down_revision(text: str) -> list[str]:
    # Match both typed (`down_revision: Union[str, None] = ...`) and
    # untyped (`down_revision = ...`) forms, anchored to start of line.
    m = re.search(r"""^down_revision\s*(?::[^=]+)?\s*=\s*(.+)""", text, re.MULTILINE)
    if not m:
        return []
    rest = m.group(1).lstrip()
    if rest.startswith("None"):
        return []
    if rest.startswith("("):
        depth = 0
        paren_end = 0
        for i, ch in enumerate(rest):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    paren_end = i + 1
                    break
        inner = rest[1 : paren_end - 1]
        return re.findall(r"""['"]([^'"]+)['"]""", inner)
    m = re.match(r"""\s*['"]([^'"]+)['"]""", rest)
    return [m.group(1)] if m else []


def test_alembic_single_head_assertion():
    migration_files = sorted(MIGRATIONS_DIR.glob("*.py"))
    revisions = {}
    parent_refs = set()

    for f in migration_files:
        text = f.read_text(encoding="utf-8")
        rev_match = _REV_RE.search(text)
        if not rev_match:
            continue
        rev = rev_match.group(1)
        revisions[rev] = f.name
        for p in _parse_down_revision(text):
            parent_refs.add(p)

    heads = [r for r in revisions if r not in parent_refs]
    assert len(heads) == 1, f"Expected 1 alembic head, got {len(heads)}: {heads}"
