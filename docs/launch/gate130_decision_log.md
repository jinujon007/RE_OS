# GATE-130 — Firecrawl Integration Decision Log
**Declared: 2026-06-24 | Status: ✅ PASSED**

## Summary

Firecrawl wired as the final fallback for `developer_scout.py` and `portal_scout.py`
when Scrapling (TLS fingerprint / stealth Playwright), raw Playwright, and requests
all fail to retrieve content from a target URL.

## Architecture

```
developer_scout._fetch_raw():
  Scrapling DynamicFetcher (use_playwright=True)  ─┐
  Scrapling HTTP Fetcher (use_playwright=False)    ─┤
  Raw Playwright (if use_playwright=True)           ─┤
  requests (if use_playwright=False)                ─┤
  → Firecrawl API (fallback)                       ◄─┘

portal_scout._scout_source():
  Scrapling DynamicFetcher (JS SPA portals)        ─┐
  Scrapling HTTP Fetcher (bot-protected portals)   ─┤
  Raw Playwright (Housing/NoBroker fallback)        ─┤
  requests (all portals fallback)                   ─┤
  → Firecrawl API (fallback)                       ◄─┘
```

## Files Created/Modified

| File | Change | Rationale |
|------|--------|-----------|
| `utils/firecrawl_client.py` | New | scrape_url() + search_query(), keyless grace, 10-req cap, thread-safe counter, 429 retry with backoff, Prometheus metrics |
| `config/settings.py` | +FIRECRAWL_API_KEY / FIRECRAWL_BASE_URL | Env-driven config with self-hosted override support |
| `config/metrics.py` | +3 Firecrawl metrics | firecrawl_requests_total, firecrawl_errors_total, firecrawl_duration_seconds |
| `scrapers/developer_scout.py` | Firecrawl fallback in _fetch_raw | Final resort after all fetchers exhaust |
| `scrapers/portal_scout.py` | Firecrawl fallback in _scout_source | Same pattern as developer_scout |
| `tests/test_firecrawl_client.py` | 8 tests | Import, no-key grace, req cap, empty content, 429 retry, import verification |
| `tests/test_gate130.py` | 5 assertions | GATE-130 declaration suite |
| `.env.example` | +FIRECRAWL_API_KEY | Documentation for new devs |
| `docs/MCP_SETUP.md` | Integration plan updated | Sprint 130, not 133 |
| `docs/launch/gate130_decision_log.md` | This file | Decision log per project convention |

## Key Design Decisions

1. **Fallback-only, not primary**: Firecrawl remains after all existing fetchers. If a URL
   renders fine with Scrapling/Playwright, Firecrawl is never called. This preserves the
   500-page/month free tier for actual breakage scenarios.

2. **Per-scout-run cap reset**: `_reset_count()` called in both `DeveloperScout.__init__`
   and `PortalScout.__init__` so each fresh scout run gets 10 Firecrawl calls. A single
   developer site taking all 10 won't starve the other scout entirely (each scout is
   a separate process/CLI invocation).

3. **Thread-safe counter**: `threading.Lock` guards the module-level `_request_count` in
   case both scrapers are called from concurrent agents (future refactor).

4. **429 retry**: Single retry with 1s backoff on rate-limit or 5xx. No exponential backoff
   needed at 10 req/run — the retry is a hedge against transient congestion, not contention.

5. **Prometheus instrumentation**: 3 metrics (counter for requests/errors, histogram for
   duration) give SLO observability into the fallback path.

## Risk Register

| Risk | Mitigation | Owner |
|------|-----------|-------|
| Firecrawl API key expires | Graceful None/[] path — no crash, just degraded fallback | Jinu (env var rotation) |
| 500-page/month exceeded mid-cycle | 10-req/run cap per scout limits burst; monthly budget covers ~50 full misses if every developer site fails | Jinu (upgrade tier) |
| Firecrawl endpoint changes | Single URL config in settings.py; httpx.HTTPStatusError caught cleanly | Dev team |
| Both scrapers fire Firecrawl in same process | Thread-safe counter prevents double-counting; worst case: one scout gets all 10 | Built-in |
