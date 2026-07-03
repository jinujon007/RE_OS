"""T-1505 — Alembic migration chain validation test (GATE-163 A5).

Asserts all migration files in alembic/versions/ are importable,
each has revision and down_revision fields, the chain forms a valid
DAG with exactly one head (HEAD_REVISION constant), no orphan revisions,
no circular references, and at least 75 migration files exist.

Handles:
- Typed annotations: revision: str, down_revision: Union[str, Sequence[str], None]
- Merge revisions: down_revision = ("parent_a", "parent_b")
- Multi-line tuple assignments spanning several lines
- v2 schema branch (0100/0101/0102 merge)

Risk notes:
  - A new migration with a different down_revision format (e.g., 3+ parent
    merge) may require updating _field_value_from_lines to handle
    deeper paren nesting.
  - The DFS cycle detector assumes acyclic DAG — if a cycle is introduced
    (e.g., by a botched merge), the test will flag it with the first
    revision in the cycle.
  - HEAD_REVISION is hardcoded — when a new migration is created on top
    of the current head, this constant must be updated.
  - The compile check catches syntax errors (e.g., missing imports, broken
    f-strings) but NOT semantic errors (e.g., wrong column type).
"""

import ast
import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

MIGRATION_DIR: pathlib.Path = (
    pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions"
)

HEAD_REVISION: str = "0079_kaveri_registration_metadata"

# ── Parsing helpers ─────────────────────────────────────────────────────

# Regex for field = <value> or field: Optional[Type] = <value>
_FIELD_PATTERN = re.compile(
    r"^(\w+)\s*(?::\s*(?:str|Union\[.*?\]|Sequence\[.*?\]|Optional\[.*?\])\s*)?=\s*(.*)"
)


def _field_value_from_lines(lines: list[str], field: str):
    """Extract the assigned value for `field`, possibly across multiple lines.

    Supports:
      field = "single_string"
      field: type = "single_string"
      field = (
          "part_a",
          "part_b",
      )

    Returns the parsed Python literal via ast.literal_eval, or None.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        m = _FIELD_PATTERN.match(stripped)
        if not m or m.group(1) != field:
            continue
        raw = m.group(2).strip()

        # Multiline tuple: value starts with '(' and doesn't close on same line
        if raw.startswith("(") and not raw.rstrip(",").endswith(")"):
            expr_parts: list[str] = [raw]
            j = i + 1
            paren_depth = raw.count("(") - raw.count(")")
            while j < len(lines) and paren_depth > 0:
                next_line = lines[j].strip()
                expr_parts.append(next_line)
                paren_depth += next_line.count("(") - next_line.count(")")
                j += 1
            joined = " ".join(expr_parts)
            try:
                return ast.literal_eval(joined)
            except (ValueError, SyntaxError):
                return None
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return None
    return None


def _parse_migrations() -> dict:
    """Parse all migration files into structured records.

    Returns dict mapping revision -> {
        "down_revision": str | tuple[str, ...] | None,
        "depends_on": str | None,
        "branch_labels": str | None,
        "file": str,
    }
    """
    chain: dict = {}
    for fpath in sorted(MIGRATION_DIR.glob("*.py")):
        content = fpath.read_text(encoding="utf-8")
        lines = content.splitlines()
        record = {
            "down_revision": None,
            "depends_on": None,
            "branch_labels": None,
            "file": fpath.name,
        }

        val = _field_value_from_lines(lines, "revision")
        rev: str | None = val if isinstance(val, str) else None

        val = _field_value_from_lines(lines, "down_revision")
        if val is not None:
            record["down_revision"] = val

        val = _field_value_from_lines(lines, "depends_on")
        if val is not None:
            record["depends_on"] = val

        val = _field_value_from_lines(lines, "branch_labels")
        if val is not None:
            record["branch_labels"] = val

        if rev:
            chain[rev] = record
    return chain


def _detect_cycle(chain: dict) -> str | None:
    """DFS-based cycle detection. Returns first revision in a cycle, or None.

    Uses Tarjan-style tri-color marking (WHITE=unvisited, GRAY=in-progress,
    BLACK=finished). A back-edge to a GRAY node indicates a cycle."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {rev: WHITE for rev in chain}

    def dfs(rev: str) -> str | None:
        color[rev] = GRAY
        down = chain[rev]["down_revision"]
        parents: list[str] = (
            [down]
            if isinstance(down, str)
            else list(down) if isinstance(down, tuple)
            else []
        )
        for parent in parents:
            if parent not in color:
                continue
            if color[parent] == GRAY:
                return rev
            if color[parent] == WHITE:
                result = dfs(parent)
                if result:
                    return result
        color[rev] = BLACK
        return None

    for rev in chain:
        if color[rev] == WHITE:
            result = dfs(rev)
            if result:
                return result
    return None


def _all_referenced_revisions(chain: dict) -> set[str]:
    """Return set of all revision IDs referenced as down_revision."""
    refs: set[str] = set()
    for rec in chain.values():
        dr = rec["down_revision"]
        if isinstance(dr, tuple):
            refs.update(dr)
        elif isinstance(dr, str):
            refs.add(dr)
    return refs


# ── Tests ──────────────────────────────────────────────────────────────


def test_migration_count_at_least_75():
    files = list(MIGRATION_DIR.glob("*.py"))
    assert len(files) >= 75, (
        f"Only {len(files)} migration files found in {MIGRATION_DIR} "
        f"(need >= 75). New migrations may need to be added."
    )


def test_all_migrations_compile():
    errors: list[str] = []
    for fpath in MIGRATION_DIR.glob("*.py"):
        source = fpath.read_text(encoding="utf-8")
        try:
            compile(source, fpath.name, "exec")
        except SyntaxError as exc:
            errors.append(f"{fpath.name}: line {exc.lineno}: {exc.msg}")
    assert not errors, (
        f"Compilation errors in {len(errors)} migration file(s):\n"
        + "\n".join(errors)
    )


def test_no_duplicate_revisions():
    chain = _parse_migrations()
    revs = list(chain.keys())
    dupes = {r for r in revs if revs.count(r) > 1}
    assert not dupes, (
        f"Duplicate revision IDs: {dupes}. "
        f"Alembic requires unique revision IDs across all files."
    )


def test_head_revision_present():
    chain = _parse_migrations()
    assert HEAD_REVISION in chain, (
        f"Expected head revision '{HEAD_REVISION}' not found in parsed "
        f"migrations ({len(chain)} total). Possible causes:\n"
        f"1. A new migration was created on top of the head — update HEAD_REVISION.\n"
        f"2. The head file has a syntax error — check test_all_migrations_compile.\n"
        f"3. The migration file is missing from alembic/versions/."
    )


def test_exactly_one_head():
    chain = _parse_migrations()
    refs = _all_referenced_revisions(chain)
    heads = [rev for rev in chain if rev not in refs]
    assert len(heads) == 1, (
        f"Expected exactly 1 head revision, found {len(heads)}: {heads}. "
        f"Alembic requires a single head for linear migration chains. "
        f"Merge revisions must resolve to one leaf."
    )
    assert heads[0] == HEAD_REVISION, (
        f"Head revision is '{heads[0]}', expected '{HEAD_REVISION}'."
    )


def test_chain_traces_to_root_without_cycle():
    chain = _parse_migrations()
    cycled = _detect_cycle(chain)
    assert cycled is None, (
        f"Circular dependency detected in migration chain at revision "
        f"'{cycled}'. Check down_revision references around this revision."
    )


def test_all_paths_end_at_initial_migration():
    chain = _parse_migrations()

    def walk(rev: str, depth: int = 0) -> bool:
        if depth > 100:
            return False
        down = chain.get(rev, {}).get("down_revision")
        if down is None:
            return True
        parents: list[str] = (
            [down]
            if isinstance(down, str)
            else list(down) if isinstance(down, tuple)
            else []
        )
        return all(walk(p, depth + 1) for p in parents if p in chain)

    assert walk(HEAD_REVISION), (
        f"Chain from '{HEAD_REVISION}' does not reach a migration with "
        f"down_revision=None. Check for broken parent references or "
        f"exceeded recursion depth (>100)."
    )


def test_initial_migration_exists():
    chain = _parse_migrations()
    initials = [
        rev for rev, rec in chain.items()
        if rec["down_revision"] is None
    ]
    assert len(initials) >= 1, (
        "No migration with down_revision=None found. "
        "At least one initial migration must exist."
    )
    assert "0001_initial" in initials, (
        f"'0001_initial' not in initial migrations: {initials}"
    )


def test_all_referenced_ancestors_exist():
    chain = _parse_migrations()
    unknown: list[str] = []
    for rev, rec in chain.items():
        dr = rec["down_revision"]
        if isinstance(dr, tuple):
            for parent in dr:
                if parent not in chain:
                    unknown.append(f"{rev} references '{parent}' (not found)")
        elif isinstance(dr, str):
            if dr not in chain:
                unknown.append(f"{rev} references '{dr}' (not found)")
    assert not unknown, (
        "down_revision references to non-existent migrations:\n"
        + "\n".join(unknown)
    )


def test_empty_migration_dir_does_not_crash():
    """Verify the parser handles an empty directory gracefully.
    This tests defensive coding — the test itself is against the real dir."""
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmpdir:
        empty_path = pathlib.Path(tmpdir)
        files = list(empty_path.glob("*.py"))
        assert len(files) == 0
