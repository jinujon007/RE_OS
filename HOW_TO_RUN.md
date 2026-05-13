# RE_OS — How To Run
**Owner: Jinu Joshi — Land & Life Space**
**Last updated: 2026-05-13**

This document tells you exactly what to do to start, run, monitor, and fix RE_OS.
No assumptions. Every command is here. Every error has a fix.

---

## What RE_OS Does (Plain English)

RE_OS is a system of 5 AI agents that work together to collect and analyse real estate data for
North Bengaluru micro-markets. You give it a market name (e.g. Yelahanka). It scrapes RERA
Karnataka, pulls live property listings, stores everything in a database, and produces a written
market intelligence report — ending with a single recommended action for LLS.

The whole thing runs inside Docker (5 containers running in the background on your machine).
You control it from the terminal.

---

## Before You Do Anything — Check Your Location

Every command in this document must be run from the project folder.
Open VS Code terminal (`Ctrl + backtick`) and run:

```powershell
pwd
```

The output must show:
```
D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS
```

If it shows something else, navigate there:

```powershell
cd "D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS"
```

Do this every time before running any command below.

---

## Part 1 — Starting the System

### Step 1.1 — Start Docker Desktop

Docker Desktop must be running before any command works.
Look for the Docker whale icon in your Windows taskbar (bottom right).
If it is not there, open Docker Desktop from the Start menu and wait until it says "Engine running".

### Step 1.2 — Start All 5 Containers

```powershell
docker compose up -d
```

The `-d` means "detached" — it runs in the background and returns your terminal to you.
First time this runs, it may take 2–5 minutes to download images. After that it is fast.

### Step 1.3 — Verify Everything is Running

```powershell
docker compose ps
```

You should see 5 rows. Every row must show `running` in the Status column:

```
NAME              STATUS
re_os_db          running
re_os_ollama      running
re_os_redis       running
re_os_agents      running
re_os_scheduler   running
```

If any container shows `exited` — see Part 4 (Troubleshooting) below.

---

## Part 2 — Running the Intelligence Pipeline

### Run for a Single Market (Start Here)

```powershell
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
```

Replace `Yelahanka` with any of these markets:
- `Yelahanka`
- `Devanahalli`
- `Hebbal`
- `Rajankunte`

### Run for All Markets at Once

```powershell
docker compose exec agents python crews/market_intel_crew.py
```

This runs all markets in sequence. Takes 15–25 minutes total.

### What Happens During a Run

The runtime pipeline has 3 stages. You will see them printed to the terminal:

```
STAGE 1/3  →  Data crew scrapes RERA Karnataka + live listings and saves checkpoints
STAGE 2/3  →  Python validator + DB organizer validates records and upserts to PostgreSQL
STAGE 3/3  →  Analyst + CEO generate intelligence brief and one strategic action
```

Total runtime: 3–5 minutes per market.

### Where the Report Goes

When the run finishes, the report is saved automatically:

```
outputs/yelahanka/intel_report_YYYYMMDD_HHMM.txt
```

Open it directly in VS Code — it contains the full market brief and the CEO recommendation.

---

## Part 3 — Watching What is Happening (Live Log)

Open a second terminal window and run:

```powershell
Get-Content logs/crew.log -Wait -Tail 50
```

This shows the last 50 lines of the log and updates live as the run progresses.
Press `Ctrl + C` to stop watching.

### What Good Logs Look Like

When everything is working correctly, you should see lines like these:

```
[Router] LIGHT tier → Cerebras llama3.1-8b (1M tok/day, fastest)
[Router] ANALYSIS tier → Cerebras llama3.1-8b (1M tok/day)
[Router] HEAVY tier → Groq meta-llama/llama-4-scout-17b-16e-instruct (30k TPM)
[Playwright] Intercepted 47 rows (total_records=47)
```

This means: Cerebras is handling light work (free, fast), Groq is handling CEO synthesis, and the
RERA scraper found real data from the portal.

### Reading Run History

To see a summary of all past runs:

```powershell
docker compose exec agents python config/run_logger.py
```

Or open `logs/runs_summary.md` directly in VS Code for a table view.

---

## Part 4 — Troubleshooting

### Problem: A Container Shows "exited" in docker compose ps

This means one container crashed on startup.

**Step 1 — Find out why:**
```powershell
docker compose logs re_os_agents --tail 30
```
Replace `agents` with whichever service showed `exited`.

**Step 2 — Restart it:**
```powershell
docker compose restart agents
```

**Step 3 — If it keeps crashing, rebuild:**
```powershell
docker compose build agents
docker compose up -d
```

---

### Problem: RateLimitError — "Limit X TPM, Used Y, Requested Z"

This means an AI provider ran out of tokens for the minute.

**What it looks like in the log:**
```
RateLimitError: Limit 30,000 TPM, Used 28,450, Requested 2,520
```

**Why it happens:** The system has 5 retries built in and will wait and retry automatically.
If it still fails after retries, the daily quota for that provider is exhausted.

**Fix — Check which key is exhausted:**
```powershell
docker compose logs agents --tail 20
```
Look at which `[Router]` line appeared before the error. That provider is exhausted.

**Fix — Restart to reset retry counters:**
```powershell
docker compose restart agents
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
```

**Fix — If Groq is exhausted, wait until midnight IST** (quota resets daily).
Meanwhile, the system will automatically fall back to Gemini → NVIDIA → OpenRouter → Ollama.

---

### Problem: "model does not exist" or "NotFoundError"

A model name in the configuration is wrong or has been renamed by the provider.

**What it looks like:**
```
NotFoundError: model llama-4-scout-instruct does not exist
```

**Fix:** Tell Claude Code and paste the exact error. The model name in `config/settings.py` or
`config/llm_router.py` needs to be updated to the correct name.

---

### Problem: "Found 0 unique projects" — RERA Scraper Returns Nothing

The scraper ran but got no data from the RERA portal. It will fall back to 8 hardcoded sample
projects automatically so the pipeline still completes.

**What it looks like in the log:**
```
RERA portal returned 0 results — using fallback sample data
```

**Why it happens:** The RERA Karnataka portal is JS-rendered. Playwright (the browser automation
tool) tries to intercept the data. If the portal is down, slow, or has changed its layout,
Playwright may return 0.

**What to do:**
1. Check if the portal itself is up: open `https://rera.karnataka.gov.in` in your browser.
2. If it is down — wait and try again later. The pipeline still works with fallback data.
3. If it is up but scraper still returns 0 — report to Claude Code with the exact log lines.

**Note:** Reports generated from fallback data are marked `source: fallback_sample`. They are
useful for testing the pipeline but the numbers may be stale. Do not use them for real decisions.

---

### Problem: "Connection refused" or "Cannot connect to database"

The database container is not running or not ready.

**Fix:**
```powershell
docker compose ps
```
Check that `postgres` shows `running`. If not:
```powershell
docker compose restart postgres
```
Wait 15 seconds, then run the crew again.

---

### Problem: "Cannot connect to Docker daemon" or Docker commands fail entirely

Docker Desktop is not running.

**Fix:** Open Docker Desktop from the Start menu. Wait until the whale icon in the taskbar stops
animating and shows "Engine running". Then try again.

---

### Problem: The Run Hangs and Nothing Happens for 10+ Minutes

An agent is stuck waiting for an LLM response.

**Fix — Kill and restart:**
Press `Ctrl + C` in the terminal to stop the run.
Then:
```powershell
docker compose restart agents
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
```

---

### Problem: "No space left on device" or Docker fails with disk error

Docker has filled your disk with container images and logs.

**Fix — Clean up Docker's unused data:**
```powershell
docker system prune -f
```
This removes stopped containers, unused images, and build cache. It does NOT delete your database.

---

## Part 5 — Stopping the System

### Stop Everything (Keeps Data)

```powershell
docker compose down
```

This stops all 5 containers but keeps the database data. Next time you run `docker compose up -d`,
everything picks up where it left off.

### Stop and Wipe Everything (Fresh Start)

**Warning: This deletes all database data.**

```powershell
docker compose down -v
```

Use this only if you want to completely reset and start from scratch.

---

## Part 6 — Testing Individual Parts

Sometimes you want to test just one piece without running the full pipeline.

### Test the RERA Scraper Alone

```powershell
docker compose exec agents python scrapers/rera_karnataka.py --market Yelahanka
```

This runs only the scraper and prints what it found. Useful to check if the portal is reachable.

### Test the Listings Scraper Alone

```powershell
docker compose exec agents python scrapers/listings_scraper.py --market Yelahanka
```

### Open the Database and Query It Directly

```powershell
docker compose exec postgres psql -U re_os_user -d re_os
```

This opens a database shell. Some useful queries:

```sql
-- See all markets and their inventory summary
SELECT * FROM v_market_inventory;

-- See all RERA projects
SELECT * FROM v_active_projects LIMIT 20;

-- See developer rankings
SELECT * FROM v_developer_scorecard;

-- Count records in each table
SELECT COUNT(*) FROM rera_projects;
SELECT COUNT(*) FROM listings;

-- Exit the database shell
\q
```

### Check What AI Models Are Available Locally (Ollama)

```powershell
docker compose exec ollama ollama list
```

### Pull the Local AI Model if Missing

```powershell
docker compose exec ollama ollama pull llama3.1:8b
```

This downloads the local model. Takes 5–10 minutes on first run (4.7 GB).

---

## Part 7 — Rebuilding After Code Changes

If Claude Code changes any Python files, the changes are live immediately — no rebuild needed.
The containers mount the project folder directly.

**The one exception:** If `Dockerfile` or `requirements.txt` changes, you must rebuild:

```powershell
docker compose build agents
docker compose up -d
```

This rebuilds only the agents container (~5 minutes). The database and other containers are unaffected.

---

## Part 8 — API Keys

All API keys live in the `.env` file in the project root. Open it in VS Code to view or edit.

| Key | Provider | What It Powers | Free Quota |
|-----|----------|---------------|------------|
| `CEREBRAS_API_KEY` | Cerebras | Scraper, Parser, Organizer, Analyst agents | 1,000,000 tokens/day |
| `GEMINI_API_KEY` | Google AI Studio | CEO fallback + Light backup | 250,000 TPM (Flash) |
| `GROQ_API_KEY` | Groq | CEO agent (primary) | 30,000 TPM, 1,000 req/day |
| `NVIDIA_API_KEY` | NVIDIA NIM | Backup for all tiers | 40 req/min |
| `OPENROUTER_API_KEY` | OpenRouter | Last resort fallback | 50–1,000 req/day |

**If a key expires or is revoked:**
1. Go to the provider's website and create a new key
2. Open `.env` and replace the old key
3. Run: `docker compose restart agents scheduler`
4. No rebuild needed — `.env` is reloaded on restart

**Key rotation sites:**
- Groq: console.groq.com → API Keys
- Cerebras: cloud.cerebras.ai → API Keys
- Gemini: aistudio.google.com → Get API Key
- NVIDIA: build.nvidia.com → API Keys
- OpenRouter: openrouter.ai → Keys

---

## Part 9 — The Scheduler (Automatic Daily Runs)

The `re_os_scheduler` container runs jobs automatically:

| Time (IST) | What it does |
|------------|-------------|
| 2:00 AM | Runs full market pipeline sweep for all target markets |
| 6:00 AM | Takes a market snapshot (records absorption rates) |
| Every 6 hours | Placeholder listings-scan job (logging only; scraper wiring pending) |

These run automatically as long as the containers are running. You do not need to do anything.

To see what the scheduler is doing:
```powershell
docker compose logs re_os_scheduler --tail 20
```

---

## Part 10 — Complete Command Reference

```powershell
# ── STACK CONTROL ──────────────────────────────────────────────────────────────
docker compose up -d                          # Start all 5 containers
docker compose down                           # Stop all (keeps data)
docker compose down -v                        # Stop all + wipe database (careful)
docker compose ps                             # Check container status
docker compose restart agents                 # Restart only the agents container
docker compose restart agents scheduler       # Restart agents + scheduler
docker compose build agents                   # Rebuild after Dockerfile changes

# ── RUNNING THE CREW ───────────────────────────────────────────────────────────
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
docker compose exec agents python crews/market_intel_crew.py --market Devanahalli
docker compose exec agents python crews/market_intel_crew.py --market Hebbal
docker compose exec agents python crews/market_intel_crew.py --market Rajankunte
docker compose exec agents python crews/market_intel_crew.py                      # all markets

# ── LOGS AND MONITORING ────────────────────────────────────────────────────────
Get-Content logs/crew.log -Wait -Tail 50      # Live log tail
Get-Content logs/crew.log -Tail 100           # Last 100 lines (no live update)
docker compose logs agents --tail 50          # Container stdout logs
docker compose logs postgres --tail 30        # Database container logs
docker compose logs scheduler --tail 20       # Scheduler logs
docker compose exec agents python config/run_logger.py   # Run history summary

# ── TESTING INDIVIDUAL PARTS ───────────────────────────────────────────────────
docker compose exec agents python scrapers/rera_karnataka.py --market Yelahanka
docker compose exec agents python scrapers/listings_scraper.py --market Yelahanka

# ── DATABASE ───────────────────────────────────────────────────────────────────
docker compose exec postgres psql -U re_os_user -d re_os    # Open DB shell
# Inside psql:
#   SELECT * FROM v_market_inventory;
#   SELECT * FROM v_active_projects LIMIT 20;
#   SELECT * FROM v_developer_scorecard;
#   \q   (to exit)

# ── OLLAMA (LOCAL AI MODEL) ────────────────────────────────────────────────────
docker compose exec ollama ollama list              # List downloaded models
docker compose exec ollama ollama pull llama3.1:8b  # Download local model

# ── CLEANUP ────────────────────────────────────────────────────────────────────
docker system prune -f                        # Remove unused Docker data (safe)
```

---

## Part 11 — How to Report an Error to Claude Code

When something breaks and you do not know what to do:

1. Run this command and copy everything it prints:
   ```powershell
   docker compose logs agents --tail 50
   ```

2. Also run:
   ```powershell
   Get-Content logs/crew.log -Tail 30
   ```

3. Paste both outputs into the Claude Code chat.

4. Say: "RE_OS broke. Here are the logs. What is wrong and how do I fix it?"

Claude Code will read the exact error message and tell you the fix.
Do not try to interpret the error yourself — paste the full output, not a summary.

---

*This file covers daily operation. For architecture, agent details, and project state — read CLAUDE.md.*
