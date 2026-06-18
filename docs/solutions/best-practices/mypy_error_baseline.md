# mypy Error Baseline — GATE-110

**Updated: 2026-06-17 | Gate: GATE-110 ? PASSED**

## Configuration

`mypy.ini` at repo root with:
- `strict_optional = True` — Optional types must be unwrapped before use
- `warn_return_any = True` — functions returning `Any` must be annotated
- `warn_unused_ignores = True` — stale `# type: ignore` comments flagged
- `follow_imports = skip` — imported files not recursively checked; avoids cascade from untyped third-party code
- 21 per-module `ignore_missing_imports = True` entries for packages without stubs (see mypy.ini)

## Scope

6 directories: `agents/`, `config/`, `crews/`, `utils/`, `intelligence/`, `ingest/`
Excluded: `tests/`, `alembic/versions/`, `scripts/`, `kilo_output/`, `kilo_logs/`

## Result

```text
Success: no issues found in 152 source files
```

## Tests

- `tests/test_mypy_strict_optional.py` — 6 per-directory subprocess mypy tests (each exit 0)
- `tests/test_gate110.py` — 4 gate assertions:
  1. `mypy.ini` exists at repo root
  2. `mypy.ini` does NOT contain `no_strict_optional = True`
  3. CI workflow does NOT contain `--no-strict-optional`
  4. `mypy agents/ --config-file mypy.ini` exits 0

## CI Integration

CI type-check job (`.github/workflows/ci.yml` line 156):
```yaml
mypy agents/ config/ crews/ utils/ intelligence/ ingest/ \
  --config-file mypy.ini
```
Removed flags: `--no-strict-optional`, `--ignore-missing-imports`.

## Adding a New Untyped Package

If a new third-party package causes `import-untyped` errors:
1. Add `[mypy-<package>.*]` section to `mypy.ini` with `ignore_missing_imports = True`
2. If the package ships type stubs, prefer `pip install types-<package>` instead
3. Run full check: `mypy agents/ config/ crews/ utils/ intelligence/ ingest/ --config-file mypy.ini`

## Residual Notes

6 `annotation-unchecked` informational notes remain (untyped function bodies not checked). These are safe — the functions are simple wrappers with `**kwargs` passthrough. They are NOT errors and do not affect the type-check gate.

## Per-Directory Error Summary

| Directory | Files | Errors | Notes |
|-----------|-------|--------|-------|
| agents/   | 5     | 0      | clean |
| config/   | 12    | 0      | clean |
| crews/    | 6     | 0      | clean |
| utils/    | 71    | 0      | clean |
| intelligence/ | 12 | 0      | clean |
| ingest/   | 46    | 0      | clean |
| **Total** | **152** | **0** | **pass** |
