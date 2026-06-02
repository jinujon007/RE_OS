# FAQ — Frequently Asked Questions

---

## General

### What is RE_OS?

RE_OS is an autonomous multi-agent AI system that scrapes RERA Karnataka, property listing portals, and the Kaveri registration system, then produces structured intelligence briefs for real estate developers making land acquisition and project decisions in North Bengaluru.

The output is not a report. It is a recommendation — one specific action per market, framed in PSF entry bands with explicit go/no-go thresholds.

### Who is it built for?

RE_OS is built for a single, specific user: an employee at Land & Life Space (LLS), a Bengaluru real estate developer-builder. It is open-sourced so other developers and analysts can adapt it to their own markets.

### Does it require paid API keys?

No. A full 3-market run (Yelahanka + Devanahalli + Hebbal) costs $0 using free-tier providers:
- **Groq** — 30k TPM free, no card required
- **Cerebras** — 1M tokens/day free, no card required
- **Gemini** — 250k TPM Flash free

Local Ollama fallback is also included. If you have an NVIDIA GPU, RE_OS will use it automatically.

---

## Setup

### The stack won't start — what do I check first?

```bash
docker compose logs agents --tail 50
```

Common causes:
- `DB_PASSWORD` not set in `.env`
- Docker Desktop not running
- Port 8050 already in use (`lsof -i :8050` or `netstat -ano | findstr 8050` on Windows)

### How long does first boot take?

3–5 minutes. The agents container runs `alembic upgrade head` and `sync_registry_to_db` before the server starts. Subsequent boots take ~15 seconds.

### Do I need to pull the Ollama model?

No — Ollama is a fallback. If you have Groq + Cerebras keys, you'll never hit Ollama during a normal run. Pull it only if you want unlimited local fallback:
```bash
docker compose exec ollama ollama pull llama3.1:8b
```

---

## Data & Accuracy

### Why does Yelahanka show only 8 fallback projects?

Known issue: the RERA Karnataka portal's Playwright selector (`No locality input found`) fails for Yelahanka and Hebbal. Fallback records are marked `[ESTIMATED]` in the output. Devanahalli works correctly (317+ live records). Fix is tracked in Sprint 40 (GATE-51).

### Where does the PSF data come from?

Three sources, reconciled:
1. **RERA Karnataka** — developer-declared PSF at project registration
2. **Portal listings** — 99acres, MagicBricks, Housing.com actual listing prices
3. **Kaveri registrations** — government-recorded transaction PSF from IGR data

### How fresh is the data?

The scheduler runs a full RERA refresh at 2 AM IST daily. Portal listings are scraped in the same run. If you run the pipeline manually, you get fresh data from that moment.

### What does [ESTIMATED] mean in the output?

A record was generated from hardcoded fallback data because the live scraper returned zero results. Treat any market-level signal based on [ESTIMATED] records as directional, not precise.

---

## Pipeline

### Can I run just one market instead of all three?

```bash
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
```

### How do I skip re-scraping and just re-run analysis?

Stage 1 checkpoints are automatically reused if they were written today. To force re-scrape:
```bash
rm outputs/yelahanka/checkpoints/*.json
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
```

### The pipeline failed halfway — do I lose all progress?

No. Stage 1 checkpoints are written as the scrapers complete. If the pipeline fails in Stage 2 or Stage 3, Stage 1 is already persisted. Re-running will skip Stage 1 and resume from Stage 2.

### How do I see what ran yesterday?

```bash
docker compose exec agents python config/run_logger.py
```
Or query directly:
```sql
SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT 20;
```

---

## Board Room

### What is the Board Room?

A virtual panel of 5 department heads (BD / Finance / Engineering / Ops / Legal) that evaluate any land acquisition pitch concurrently. Each head uses real DB data — not LLM knowledge. Total runtime ~90 seconds.

### How do I run a Board Room evaluation?

```bash
# Via API:
curl -X POST http://localhost:8050/api/board/run \
  -H "X-API-Key: $DASHBOARD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"market": "Yelahanka", "pitch": "5-acre R2 site, target ₹6500 PSF"}'

# Via make:
make board MARKET=Yelahanka PITCH="5-acre R2 site, target ₹6500 PSF"
```

### What data does Finance Head use for IRR?

Live DB data: current market PSF (from `v_market_inventory`), absorption rate, comparable guidance values from `kaveri_registrations`. The IRR model (`utils/irr_model.py`) uses standard developer economics: land cost + construction cost + margin = GDV.

---

## LLM & Costs

### Which LLM is used by which agent?

See [ARCHITECTURE.md — LLM Routing](ARCHITECTURE.md#llm-routing).

Short version:
- CEO: Groq llama-4-scout (HEAVY tier)
- Analyst: Cerebras 8B (ANALYSIS tier)  
- Scraper: Cerebras 8B (LIGHT tier)
- Fallback for all: Ollama (local)

### What happens when a provider is rate-limited?

The LLM router (`config/llm_router.py`) automatically marks that provider as excluded for the current run and falls back to the next tier. A full run can complete even if 3 of 5 providers are unavailable.

---

## Extending RE_OS

### How do I add a new market?

1. Add keywords to `config/settings.py → MARKET_RERA_KEYWORDS`
2. Update `TARGET_MARKETS` in `.env`
3. The 16-table schema already supports multi-city — `micro_markets` has `city` and `state` columns

### How do I add a new data source?

1. Create a scraper in `scrapers/` that returns a list of structured dicts
2. Register it as a tool in `agents/scraper_agent.py`
3. Add DB upsert logic to `utils/db_organizer.py`
4. Write tests — new scrapers must handle zero results without raising

### How do I hire a new agent?

See [docs/agents.md — Hiring New Agents](docs/agents.md#hiring-new-agents). No Python or Docker rebuild required — define in YAML, hire from dashboard.

---

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md).

For bugs: always include `docker compose logs agents --tail 50` output.
For features: check [VISION.md](VISION.md) and [ROADMAP.md](ROADMAP.md) first.
