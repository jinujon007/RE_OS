# RE_OS — MCP Server Setup Guide
**Last updated: 2026-06-19**

Complete setup guide for all MCP servers wired into RE_OS. MCPs extend Claude Code with live tools — database queries, web search, geospatial scoring, dashboard reads, and vault sync.

---

## Status Overview

| MCP | Scope | Status | Key Required |
|-----|-------|--------|-------------|
| `filesystem-vault` | User | ✅ LIVE | No |
| `obsidian` | User | ✅ LIVE | No |
| `tavily` | User | ✅ LIVE (tools load, queries need key) | Yes |
| `sequential-thinking` | User | ✅ LIVE | No |
| `postgres` | Project | ✅ LIVE when Docker up | No |
| `fetch` | User | ✅ LIVE | No |
| `firecrawl` | User | ✅ configured, needs key | Yes |
| `google-maps` | User | ✅ configured, needs key | Yes |
| `brave-search` | User | ✅ configured, needs key | Yes |
| `grafana` | Project | ✅ configured, needs Docker + API key | Yes |
| `propcontext` | Project | ⚠️ PLACEHOLDER — find URL | No |

---

## Section 1 — Immediate (No Keys Required)

### PostgreSQL MCP
Lets Claude query RE_OS database directly in conversation. Tables, views, all 16 schemas.

**Requirement:** Docker stack must be running (`docker compose up -d`).

**Connection:** `postgresql://re_os_user:re_os_2024@localhost:5432/re_os`
Port `127.0.0.1:5432` exposed on loopback — safe, not external.

**Test in Claude Code:**
```
What's in the v_market_inventory view?
```

### Obsidian MCP
Syncs RE_OS intel outputs directly to your Obsidian vault at `D:/Brain/JINU JOSHI`.

**Automatic** — no setup. Vault path is hardcoded.

**Use:** After a Board Room session, ask Claude to write the verdict to `03 LLS/01 Wiki/syntheses/`.

### filesystem-vault
Read/write access to the full Obsidian vault for Claude. Broader than Obsidian MCP.

**Automatic** — no setup. Same path `D:/Brain/JINU JOSHI`.

### sequential-thinking
Structured reasoning chain tool — used by CEO agent for multi-step analysis. No API key.

**Automatic** — no setup.

---

## Section 2 — Needs API Keys (Free Tiers Available)

### Tavily (Deep Research Search)
**Why:** Real-time web search for market news, developer announcements, regulatory changes.
**Free tier:** 1,000 searches/month — enough for weekly pipeline enrichment.

**Steps:**
1. Go to `https://tavily.com`
2. Sign up → Dashboard → API Keys → Create key
3. Open `.env` in RE_OS root
4. Set: `TAVILY_API_KEY=tvly-your-key-here`
5. In Windows: `[System.Environment]::SetEnvironmentVariable("TAVILY_API_KEY", "tvly-...", "User")`
6. Restart Claude Code

**Test:**
```
Use Tavily to search for "Devanahalli real estate 2026 market update"
```

**Integration (GATE-131 ✅ 2026-06-24):** Tavily wired as primary search source in `news_scout.py` (Source 0 before Google News RSS) and as live enrichment backend in `IntelSearchTool` (ChromaDB semantic + Tavily, dedup by URL). Monthly quota guard (warn 800, stop 950) persisted to JSON checkpoint. See `utils/tavily_client.py`.

---

### Brave Search
**Why:** Alternative to Tavily — independent search index, great for developer news + competitor tracking.
**Free tier:** 2,000 queries/month.

**Steps:**
1. Go to `https://brave.com/search/api/`
2. Sign up → Get Started → Create API key (free tier)
3. Set: `BRAVE_API_KEY=BSA-your-key`
4. Windows env: `[System.Environment]::SetEnvironmentVariable("BRAVE_API_KEY", "BSA-...", "User")`
5. Restart Claude Code

---

### Firecrawl (Battle-Tested Web Scraper)
**Why:** Replaces brittle custom scrapers for portal_scout and developer_scout. Handles JS-heavy sites, anti-bot, returns clean markdown. Anthropic uses it.
**Free tier:** 500 pages/month (sufficient for weekly developer site checks).

**Steps:**
1. Go to `https://firecrawl.dev`
2. Sign up → Dashboard → API Keys → Generate
3. Set: `FIRECRAWL_API_KEY=fc-your-key`
4. Windows env: `[System.Environment]::SetEnvironmentVariable("FIRECRAWL_API_KEY", "fc-...", "User")`
5. Restart Claude Code

**Integration (GATE-130 ✅ 2026-06-24):** Firecrawl wired as final fallback in `developer_scout.py` and `portal_scout.py` after Scrapling/Playwright/requests all exhaust. See `utils/firecrawl_client.py`.

---

### Google Maps (Commute Scoring for Corridor Analysis)
**Why:** Corridor scorer currently uses PostGIS straight-line distance. Google Maps adds real drive-time from a site to Hebbal IT corridor / Manyata / Airport — more meaningful for buyer appeal scoring.
**Cost:** Free $200/month credit covers ~40,000 distance matrix requests — more than enough.

**Steps:**
1. Go to `https://console.cloud.google.com`
2. Create project "RE_OS" (or use existing)
3. Enable APIs: Maps JavaScript API, Geocoding API, Distance Matrix API, Places API
4. Credentials → Create Credentials → API Key
5. Restrict key: Application restrictions = None (server), API restrictions = the 4 above
6. Set: `GOOGLE_MAPS_API_KEY=AIza-your-key`
7. Windows env: `[System.Environment]::SetEnvironmentVariable("GOOGLE_MAPS_API_KEY", "AIza-...", "User")`
8. Restart Claude Code

**Integration plan (Sprint 134):** Add `CommuteScorer` tool to CorridorScorer — drive-time to Manyata/KIAL/Hebbal as buyer-facing score.

---

## Section 3 — Needs Docker Running

### Grafana MCP (Dashboard Querying from Claude)
**Why:** Ask "what's the PSF trend for Yelahanka last 7 days?" and get answer from live Grafana panel.

**Steps:**
1. Generate Grafana service account token:
   ```
   # Open http://localhost:3000 in browser
   # Admin → Service Accounts → Add service account
   # Name: claude-mcp, Role: Viewer
   # Add token → Copy value
   ```
2. Set in `.env`: `GRAFANA_API_KEY=glsa_your-token`
3. Start the Grafana MCP container:
   ```powershell
   docker compose up -d grafana-mcp
   ```
4. Verify: `curl http://localhost:8010/sse` should return SSE headers
5. Project-level MCP is already configured at `http://localhost:8010/sse`

**Test (with Docker up):**
```
Query the Grafana dashboard for market PSF trends this week
```

---

### PropContext — Bangalore RERA MCP (Competitor Intelligence)
**Why:** Independent RERA data source — cross-reference against RE_OS's own scraped data. Verify coverage gaps. Also: monitor what competitors using Claude + PropContext can see vs. what RE_OS sees.
**No API key required** — remote hosted MCP.

**Steps to find URL:**
1. Go to `https://mcp.so` → search "PropContext"
2. Open the listing → find "MCP URL" or "SSE URL" on the detail page
3. Copy the URL (format: `https://mcp.propcontext.in/sse` or similar)
4. Edit `.claude/settings.json` → update `propcontext.url` from `PLACEHOLDER_SET_...` to real URL
5. Run: `claude mcp list` to verify connection

**Current config:** `.claude/settings.json` → `mcpServers.propcontext` → url = PLACEHOLDER

---

## Section 4 — Future MCPs (Phase 10+)

| MCP | When | Why |
|-----|------|-----|
| **Google Sheets** | Sprint 136 | Export Board Room verdicts + market_snapshots to investor-shareable Sheet |
| **MDMagic** | Sprint 137 | Branded PDF/DOCX from Intel Report markdown |
| **NotifyHub** | Sprint 138 | Multi-channel alerts: Email + WhatsApp + Telegram from one MCP call |
| **ArcGIS** | Phase 10 | Professional GIS — upgrade PostGIS corridor to ArcGIS spatial analysis |
| **TimescaleDB** | Phase 10 | Time-series optimized Postgres for market_snapshots >1M rows |
| **Sentry MCP** | Phase 10 | Error tracking from within Claude sessions |
| **AgentCron** | Phase 10 | Remote scheduled tasks as backup to APScheduler |

---

## Section 5 — RE_OS as MCP Server (Strategic Priority)

The moat insight from the MCP market audit (2026-06-19): PropContext does surface-level RERA lookup. RE_OS has 119-gate deep intelligence infrastructure that PropContext can't touch.

**The move:** Expose RE_OS itself as an MCP server. Every tool becomes callable by Claude users in Bengaluru.

Target tools to expose via MCP:
- `run_pipeline(market)` — trigger full 3-stage pipeline
- `board_room_verdict(pitch, market)` — 5-dept analysis  
- `corridor_score(lat, lon)` — composite corridor score
- `psf_forecast(market, months)` — PSFForecaster output
- `feasibility(land_cost, area_acres, market)` — quick IRR check
- `rera_search(query)` — semantic RERA search

**Sprint:** T-1380+ (Phase 10 planning)

---

## Quick Reference

```powershell
# Set a Windows environment variable permanently (User scope)
[System.Environment]::SetEnvironmentVariable("KEY_NAME", "key-value", "User")

# Verify it's set
[System.Environment]::GetEnvironmentVariable("KEY_NAME", "User")

# Check MCP status
claude mcp list

# Add a new MCP (user scope)
claude mcp add --scope user <name> -- npx -y <package>

# Add with env var
claude mcp add --scope user <name> -e API_KEY=value -- npx -y <package>

# Remove an MCP
claude mcp remove --scope user <name>
```
