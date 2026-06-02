# Getting Started

This guide takes you from zero to a working RE_OS intelligence scan in under 10 minutes.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Docker Desktop | [Download](https://www.docker.com/products/docker-desktop/) — needs to be running |
| At least one LLM API key | Groq free tier recommended (no card, no phone) |
| 8 GB free disk space | Docker images + Ollama model (~5 GB) |
| 4 GB free RAM | Minimum for the full stack |

You do **not** need Python installed locally — everything runs inside Docker.

---

## Step 1: Clone and configure

```bash
git clone https://github.com/jinujon007/RE_OS.git
cd RE_OS
cp .env.example .env
```

Open `.env` in any text editor. At minimum, set:

```env
DB_PASSWORD=choose_any_secure_password
GROQ_API_KEY=gsk_your-key-here
```

Get a free Groq key at [console.groq.com](https://console.groq.com) — no card required.

Optional but recommended — add more providers for fallback:

```env
CEREBRAS_API_KEY=csk_your-key-here   # 1M tokens/day free
GEMINI_API_KEY=AIza_your-key-here    # Flash 250k TPM free
```

---

## Step 2: Start the stack

```bash
docker compose up -d
```

First boot takes 3–5 minutes (image pulls + database init). Check all 7 containers are running:

```bash
docker compose ps
```

Expected output:
```
NAME               STATUS
re_os_agents       running (healthy)
re_os_db           running (healthy)
re_os_ollama       running
re_os_redis        running
re_os_scheduler    running
re_os_prometheus   running
re_os_grafana      running
```

If `re_os_agents` shows `starting` for more than 2 minutes, check logs:
```bash
docker compose logs agents --tail 30
```

---

## Step 3: (Optional) Pull local LLM

This gives you an unlimited local fallback when API quotas are exhausted. Download is ~5 GB.

```bash
docker compose exec ollama ollama pull llama3.1:8b
```

Skip this step if you have sufficient API quota — the system will use cloud providers only.

---

## Step 4: Run your first scan

```bash
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
```

Runtime: 3–5 minutes for a single market. You'll see progress in the terminal.

Report saved to: `outputs/yelahanka/intel_report_YYYYMMDD_HHMM.txt`

---

## Step 5: Open the dashboard

Go to [http://localhost:8050](http://localhost:8050) in your browser.

You'll see:
- **Org Chart** — your agent team
- **Intel Board** — the latest market brief
- **DB Explorer** — live data from the pipeline

---

## Step 6: Query the database directly

```bash
docker compose exec postgres psql -U re_os_user -d re_os
```

```sql
-- Market snapshot
SELECT * FROM v_market_inventory;

-- Grade A developers in Yelahanka
SELECT d.name, d.grade, d.total_units_launched
FROM developers d
JOIN rera_projects r ON r.developer_id = d.id
JOIN micro_markets m ON m.id = r.micro_market_id
WHERE m.slug = 'yelahanka' AND d.grade = 'A';

-- Absorption rate
SELECT market_name, active_projects, avg_psf, absorption_rate, months_of_supply
FROM v_market_inventory;
```

---

## Running All Three Markets

```bash
docker compose exec agents python crews/market_intel_crew.py
```

Runs Yelahanka → Devanahalli → Hebbal sequentially. Total runtime: ~12–15 minutes.

---

## Common Issues

### `re_os_agents` container exits immediately
Check: `docker compose logs agents --tail 50`
Common cause: missing `DB_PASSWORD` in `.env`.

### RERA scraper returns "8 fallback projects" for Yelahanka
Known issue — RERA portal selector `No locality input found`. Output is marked `[ESTIMATED]`.
Use Devanahalli for reliable live data while this is being fixed (317 live projects as of 2026-06-02).

### Groq rate-limit error
The system will automatically fall back to Gemini → NVIDIA → Ollama. No action needed.
If all providers are exhausted: `docker compose exec ollama ollama pull llama3.1:8b` and re-run.

### Dashboard shows blank
Wait 30 seconds after `docker compose up -d` — the FastAPI server needs time to start after Alembic migrations complete.

---

## Next Steps

- [API Reference](api-reference.md) — all `/api/*` endpoints
- [Agents](agents.md) — what each agent does and how to extend them
- [Deployment](deployment.md) — running on a VPS or cloud VM
- [ARCHITECTURE.md](../ARCHITECTURE.md) — deep technical reference
