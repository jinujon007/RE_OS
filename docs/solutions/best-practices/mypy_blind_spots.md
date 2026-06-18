# mypy Blind Spots Audit

**Audited:** 2026-06-18 | **Next review:** 2026-09-18 (quarterly) | **Owner:** Kilo Code
**Scope:** All `[[mypy-<package>.*]]` sections in `mypy.ini` with `ignore_missing_imports = True`

## Risk Register Summary

| Severity | Count | Action |
|----------|-------|--------|
| HIGH (DB/Serialization) | 3 | TODO-STUB comments in `mypy.ini`. Remove ignores when stubs available. |
| MED (Hot path) | 6 | Runtime integration tests provide coverage. Monitor for stub availability. |
| LOW (Infrequent/CLI) | 12 | Acceptable risk. Re-evaluate quarterly. |

**Next review:** 2026-09-18 — check if any of the 21 packages now ship typeshed stubs
(`pip install types-<pkg>` or upstream PEP 561). Remove `ignore_missing_imports` section
for any package that gains stubs.

## Risk Heuristics

| Level | Criterion |
|-------|-----------|
| HIGH  | Package touches auth, DB, or serialization |
| MED   | Package is in a hot path (called on every pipeline run) |
| LOW   | Test-only, CLI-only, or infrequently used package |

## Package Table

| Package | Reason Skipped | Risk | Mitigation |
|---------|---------------|------|------------|
| apscheduler | No stubs. APScheduler uses dynamic dispatch patterns mypy cannot model. | MED | Confidence via integration tests. All jobs wrapped in `safe_job()`. |
| chromadb | No stubs. Dynamic client factory. | **HIGH** | Add type:ignore on each `chromadb` call site. Wrap all access in `IntelEmbedder` class. |
| crewai | No stubs. Dynamic agent/task builder pattern. | MED | Type-check via crew execution tests. Pipeline errors caught at integration level. |
| empyrical | No stubs. Pure financial-calculation calls only. | LOW | Function return types documented inline. |
| esda | No stubs. Spatial statistics — infrequent use. | LOW | Used in PySAL pipeline only. |
| evaluate | No stubs. HuggingFace evaluate library. | LOW | Only used in weekly BERTScore job. |
| fitz (PyMuPDF) | No stubs. C-extension PDF parser. | MED | All PDF parsing wrapped in scraper classes with unit tests. |
| geopandas | No stubs. GeoDataFrame access patterns vary. | MED | Used in corridor scoring and spatial queries. |
| langchain | No stubs. Dynamic chain builder. | MED | All LLM calls go through `config/llm_router.py`. |
| libpysal | No stubs. Spatial weights library. | LOW | Infrequent — used in PySAL pipeline. |
| networkx | No stubs. Graph analysis. | LOW | Used in assembly detection only. |
| numpy_financial | No stubs. Thin wrapper over numpy functions. | LOW | Single-purpose IRR/NPV calculator. |
| osmnx | No stubs. OpenStreetMap downloader. | LOW | Used only in mobility scout (monthly). |
| pandas | No stubs. Extremely dynamic DataFrame API. | MED | Ubiquitous in data processing. All pandas usage wrapped in typed helper functions. |
| pandana | No stubs. Network analysis. | LOW | Used in accessibility scoring (monthly). |
| pdfplumber | No stubs. PDF table extractor. | MED | All PDF parsing wrapped in scraper classes with unit tests. |
| psycopg2 | No stubs. Raw SQL execution. | **HIGH** | Migrate to SQLAlchemy `text()` everywhere. DB access goes through `utils/db.py`. |
| rouge_score | No stubs. Text evaluation metric. | LOW | Only used in BERTScore eval. |
| sentence_transformers | No stubs. ML inference API. | LOW | Only used in embedding pipeline. |
| shapely | No stubs. C-extension geometry. | LOW | All geometry operations wrapped in typed utility functions. |
| yaml | No stubs. Serialization library. | **HIGH** | Use `yaml.safe_load` only. All YAML config files validated by tests. |

## Action Items for HIGH-Risk Packages

### psycopg2 — DB Driver
- **Risk:** Misuse could cause SQL injection, connection leaks, or transaction errors without mypy catching it.
- **Current usage:** Mostly replaced by SQLAlchemy `text()` via `utils/db.py`. Verify no direct `psycopg2` calls remain.
- **Target:** Remove `ignore_missing_imports` once all `psycopg2` direct imports are eradicated.

### chromadb — Vector Database
- **Risk:** API misuse (wrong collection name, wrong embedding dimension) silently creates empty search results.
- **Current usage:** Wrapped in `utils/embedder.py` IntelEmbedder class.
- **Target:** Add type stubs or type:ignore on each chromadb call.

### yaml — Serialization
- **Risk:** `yaml.load()` without `Loader=yaml.SafeLoader` is a security vulnerability. Blind-spot suppression masks this at type-check level.
- **Current usage:** All yaml calls use `yaml.safe_load` per review.
- **Target:** Pin to `yaml.safe_load` usage and remove ignore once stubs exist.
