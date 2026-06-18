"""GATE-113 declaration — Test Suite Integrity.

5 assertions:
1. pytest tests/test_dashboard_routes.py exits 0
2. _LINEAR_SEED_DATA is not referenced in any test file (uses LINEAR_SEED_DATA import)
3. tests/fixtures/seed_data.py exists
4. CI workflow file contains the no-new-skips gate step
5. All pytest.mark.skip / skipif / xfail carry a # TRACK: comment
"""

import ast
import os
import subprocess
import pytest

pytestmark = pytest.mark.unit


def _read_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return None


# ═══════════════════════════════════════════════════════════════════════
# Assertion 1 — dashboard routes all green
# ═══════════════════════════════════════════════════════════════════════


def test_dashboard_routes_all_pass():
    """Assertion 1: ``pytest tests/test_dashboard_routes.py --tb=no -q`` exits 0."""
    result = subprocess.run(
        ["pytest", "tests/test_dashboard_routes.py", "--tb=no", "-q"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"test_dashboard_routes.py FAILED (exit {result.returncode}):\n"
        f"{result.stderr[-500:]}\n{result.stdout[-500:]}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Assertion 2 — _LINEAR_SEED_DATA extracted to single fixture
# ═══════════════════════════════════════════════════════════════════════


def test_linear_seed_data_not_duplicated():
    """Assertion 2: no test file defines or references ``_LINEAR_SEED_DATA``.

    After T-1253 the constant lives in ``tests/fixtures/seed_data.py`` as
    ``LINEAR_SEED_DATA`` (no leading underscore).  Any remaining reference
    to the old name is a leak from an un-migrated file.
    """
    tests_dir = os.path.join(os.path.dirname(__file__))
    # Use AST to find every identifier reference, avoiding docstring/comment noise
    found: list[tuple[str, int, str]] = []

    for root, _dirs, files in os.walk(tests_dir):
        for fn in files:
            if not fn.endswith(".py") or fn == "test_gate113.py":
                continue
            fpath = os.path.join(root, fn)
            try:
                with open(fpath, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=fpath)
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                # Check Name nodes (variable references)
                if isinstance(node, ast.Name) and node.id == "_LINEAR_SEED_DATA":
                    found.append((fpath, node.lineno, "name reference"))
                # Check string literals that aren't docstrings
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and "_LINEAR_SEED_DATA" in node.value:
                    found.append((fpath, node.lineno, f"string literal: {node.value[:60]}"))

    assert len(found) == 0, (
        f"Found {len(found)} residual reference(s) to old name ``_LINEAR_SEED_DATA``:\n"
        + "\n".join(f"  {fp}:{ln}: {ctx}" for fp, ln, ctx in found)
    )


# ═══════════════════════════════════════════════════════════════════════
# Assertion 3 — fixture file exists
# ═══════════════════════════════════════════════════════════════════════


def test_seed_data_fixture_exists():
    """Assertion 3: ``tests/fixtures/seed_data.py`` is present."""
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "seed_data.py"
    )
    assert os.path.exists(fixture_path), (
        f"Missing fixtures/seed_data.py (expected at {fixture_path})"
    )


# ═══════════════════════════════════════════════════════════════════════
# Assertion 4 — CI workflow gates new skips
# ═══════════════════════════════════════════════════════════════════════


def test_ci_workflow_has_check_no_new_skips():
    """Assertion 4: CI workflow contains the 'Check no new skip/xfail' step."""
    ci_path = os.path.join(
        os.path.dirname(__file__), "..", ".github", "workflows", "ci.yml"
    )
    content = _read_file(ci_path)
    assert content is not None, f"CI workflow not found at {ci_path}"
    assert "Check no new skip/xfail without TRACK comment" in content, (
        "CI workflow missing 'Check no new skip/xfail without TRACK comment' step — "
        "add the no-new-skips gate to .github/workflows/ci.yml"
    )


# ═══════════════════════════════════════════════════════════════════════
# Assertion 5 — every existing skip/xfail has a TRACK annotation
# ═══════════════════════════════════════════════════════════════════════


def _is_pytest_mark_decorator(node: ast.expr) -> bool:
    """Return True when *node* represents ``pytest.mark.skip`` / ``skipif`` / ``xfail``.

    Matches both the decorator form (``@pytest.mark.skip(...)``) and the
    assignment form (``pytestmark = pytest.mark.skipif(...)``).
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in ("skip", "skipif", "xfail")):
        return False
    # ``pytest.mark`` is represented as Attribute(Attribute(Name), 'mark')
    return (
        isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "pytest"
    )


def _find_track_violations(tests_dir: str) -> list[tuple[str, int, str]]:
    """Walk *tests_dir* and return every pytest.mark.skip/skipif/xfail without ``# TRACK:``.

    Covers three AST forms:

    * **Decorators** — ``@pytest.mark.skipif(...)`` lives in
      ``FunctionDef`` / ``ClassDef`` / ``AsyncFunctionDef`` decorator lists.
    * **Module-level assignment** — ``pytestmark = pytest.mark.skipif(...)``
      is an ``Assign`` or ``AnnAssign`` node.
    * **Toplevel call** — ``pytest.mark.skip("T-436 — …")`` is an ``Expr``
      whose value is a ``Call``.
    """
    violations: list[tuple[str, int, str]] = []

    for root, _dirs, files in os.walk(tests_dir):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            fpath = os.path.join(root, fn)
            try:
                with open(fpath, encoding="utf-8") as fh:
                    content = fh.read()
                    tree = ast.parse(content, filename=fpath)
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue

            lines = content.splitlines()

            def _check_line(lineno: int) -> None:
                """Record a violation if the line *lineno* has no TRACK comment."""
                raw = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
                if "# TRACK:" not in raw and "# noqa: track" not in raw:
                    violations.append((fpath, lineno, raw.strip()[:100]))

            # ── Form 1: decorators ──────────────────────────────────
            for node in ast.walk(tree):
                for target in ("decorator_list",):
                    deco_list = getattr(node, target, None) or []
                    for deco in deco_list:
                        if _is_pytest_mark_decorator(deco):
                            _check_line(deco.lineno)

            # ── Form 2: Assign / AnnAssign (e.g. ``pytestmark = …``) ─
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = getattr(node, "value", None)
                    if value is not None and _is_pytest_mark_decorator(value):
                        _check_line(node.lineno)

            # ── Form 3: standalone ``Expr(Call)`` (e.g. embedded in fn body) ─
            for node in ast.walk(tree):
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    if _is_pytest_mark_decorator(node.value):
                        # Verify it's NOT a decorator (already caught by Form 1)
                        is_deco = False
                        for parent in ast.walk(tree):
                            if hasattr(parent, "decorator_list") and node.value in parent.decorator_list:
                                is_deco = True
                                break
                        if not is_deco:
                            _check_line(node.lineno)

    return violations


def test_existing_skips_have_track_comments():
    """Assertion 5: every ``pytest.mark.skip`` / ``skipif`` / ``xfail`` carries ``# TRACK:``.

    Scans all ``.py`` files under ``tests/`` using three AST patterns:

    1. **Decorator form** — ``@pytest.mark.skipif(...)`` on a function/class.
    2. **Assignment form** — ``pytestmark = pytest.mark.skipif(...)`` at module level.
    3. **Standalone call** — ``pytest.mark.skip("…")`` as a statement.

    Files in ``tests/test_gate104_ci_coverage.py`` contain the *string*
    ``pytest.mark.skip`` inside docstrings and assert messages; these are
    correctly ignored because they are not ``ast.Call`` nodes with the
    ``pytest.mark`` attribute chain.
    """
    tests_dir = os.path.join(os.path.dirname(__file__))
    missing = _find_track_violations(tests_dir)
    assert len(missing) == 0, (
        f"Found {len(missing)} pytest.mark.skip/skipif/xfail without ``# TRACK:`` comment.\n"
        "Add ``  # TRACK: <ticket-or-reason>`` to every skip/xfail.\n"
        + "\n".join(f"  {fp}:{ln}: {txt}" for fp, ln, txt in missing)
    )
