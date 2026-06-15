# Sprint 77 — 3-Round Quality Review

**Date:** 2026-06-08 | **Reviewer:** Kilo Code | **Scope:** T-1061 → T-1067 (GATE-77)

---

## Round 1 — Full Audit: 14 Findings

| # | Severity | File | Finding | Status |
|---|----------|------|---------|--------|
| 1 | Critical | `rera_karnataka.py:472` | `_parse_html_table` uses `"source"` but rest of codebase expects `"data_source"` | FIXED R2 |
| 2 | Critical | `rera_detail_scout.py:65` | Unused `_SESSION_COOKIE` module variable — dead code | FIXED R2 |
| 3 | Critical | `rera_karnataka.py:312` | Inline import `send_scraper_alert` on every fallback — silent failure if import breaks | FIXED R2 |
| 4 | Critical | cross-file | Dual `source`/`data_source` keys in project dicts cause inconsistent fallback detection | FIXED R2 |
| 5 | Medium | `settings.py:123` | `RERA_USE_PLAYWRIGHT_MARKETS` lacks `Final` annotation — mutable at runtime | FIXED R2 |
| 6 | Medium | `rera_karnataka.py:330` | `cookies` variable could raise `UnboundLocalError` in edge paths | FIXED R2 |
| 7 | Medium | `rera_karnataka.py:338` | `_log_agent_run` never called on fallback path — blind spot in monitoring | FIXED R2 |
| 8 | Medium | `rera_karnataka.py:317` | No rate-limiting on Discord FALLBACK_SEED alerts — alert fatigue risk | FIXED R2 |
| 9 | Medium | `test_rera_live.py:527` | `test_playwright_parses_response_correctly` can write checkpoint files to disk | FIXED R2 |
| 10 | Minor | `rera_karnataka.py:7` | Module docstring says "no Playwright needed" — outdated | FIXED R2 |
| 11 | Minor | `rera_karnataka.py:724` | `_FakeCookie` class redefined on every Playwright call | FIXED R2 |
| 12 | Minor | `rera_karnataka.py:119` | `_log_agent_run` failure logged at DEBUG — should be WARNING | FIXED R2 |
| 13 | Minor | `rera_locality_audit.md` | References "AJAX JSON" — portal returns server-rendered HTML | FIXED R2 |
| 14 | Minor | `test_rera_live.py:335` | Fallback detection checks `source` and `data_source` — redundant after normalization | FIXED R2 |

---

## Round 2 — Fixes Applied (14/14)

| # | Change | Rationale |
|---|--------|-----------|
| 1 | `_parse_html_table`: `"source"` → `"data_source"` | Consistency with extractor model, plugin, and organizer |
| 4 | `_fallback_rera_data`: `"source"` → `"data_source"` | Same — single key across all code paths |
| 4 | `scrape_market` fallback detection simplified | Now only checks `data_source` |
| 2 | Removed `_SESSION_COOKIE` module variable | Dead code — only instance-level `self._session_cookie` used |
| 5 | Added `RERA_ALERT_COOLDOWN_SECONDS` to settings | Configurable rate-limit constant |
| 6 | `cookies = []` initialized before conditional paths | Prevents `UnboundLocalError` |
| 7 | `_log_agent_run` called on fallback before early return | Sealed monitoring blind spot |
| 8 | `_should_fire_fallback_alert()` + `_cleanup_stale_alert_tracking()` | Rate-limited to 1 alert/hour/market; dict bounded to 100 entries |
| 9 | `Checkpointer` mocked in playwright test | Prevents accidental disk writes |
| 10 | Docstring updated with Playwright path | Accurate strategy documentation |
| 11 | `_FakeCookie` promoted to module-level class | Once definition, not per-call |
| 12 | `logger.debug` → `logger.warning` on agent_runs failure | Proper alerting on health metric failure |
| 13 | Audit doc: "AJAX navigation" → "server-rendered HTML results" | Accuracy |
| 14 | Simplified fallback check to single key | Cleaner after normalization |

### Tests updated:
- `test_fallback_source_is_fallback_sample` — use `data_source` key
- `test_fallback_source_not_live` — use `data_source` key
- `test_discord_scraper_alert_fires_on_rera_fallback` — clear rate-limit state, use `data_source`
- `test_scraper_has_no_playwright_in_listing` → `test_post_search_has_no_playwright` — narrower scope

---

## Round 3 — Elite Polish

### Type safety
- `_validate_positive()` input guard on all metric logging
- Constants extracted: `_PW_NAVIGATE_TIMEOUT`, `_PW_FORM_FILL_DELAY`, `_PW_RESULTS_DELAY`, `_PW_DROPDOWN_DELAY`

### Error boundaries
- `_playwright_scrape` now catches `PlaywrightTimeout` at each stage (navigation, dropdown, submission) with specific log messages and `browser.close()` cleanup
- Graceful degradation on each step failure: navigates back to caller for seed fallback

### Memory safety
- `_cleanup_stale_alert_tracking()` clears rate-limit dict at 100 entries to prevent unbounded growth

### Logging quality
- All Playwright log messages include `market_name` for cross-reference
- agent_runs failures promoted to WARNING

### Data integrity
- `standalone_runner` now uses `data_source` key (was `source`)
- Downstream `rera_plugin.py` confirmed compatible (uses `data_source`)

### Remaining risks
| Risk | Mitigation |
|------|------------|
| Playwright container not deployed | Falls through to seed; Discord alert fires |
| RERA portal form structure changes | Selector-based (not positional); logs capture failure at each step |
| Rate-limit dict memory leak (edge: 100+ markets) | `_cleanup_stale_alert_tracking` clears at 100 entries |
| agent_runs DB connection failure | `_log_agent_run` catches all exceptions; returns cleanly |

---

## Verification

- **78 tests pass** (65 RERA + 6 GATE-77 + 7 Discord)
- **ruff:** All checks passed
- **py_compile:** All 7 files compile clean
- **`test_gate77.py`:** 6/6 assertions pass — GATE-77 ✅
