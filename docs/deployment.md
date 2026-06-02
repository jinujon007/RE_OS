# Deployment Guide

RE_OS is designed for single-machine deployment. The full stack runs on a laptop (tested: RTX 3050, 16 GB RAM, Windows 11) or any Linux VPS with 4+ GB RAM.

---

## Local (Docker Desktop)

See [Getting Started](getting-started.md). This is the primary deployment target.

**Hardware minimum:**
- 4 GB RAM (8 GB recommended)
- 4 GB free disk for images
- Additional 5 GB if pulling the Ollama model

**Hardware tested:**
- Intel i5-12450H, 16 GB DDR5, RTX 3050 4 GB VRAM (CUDA 12.5)
- Ollama runs on GPU — first token < 2s for llama3.1:8b

---

## Linux VPS / Cloud VM

Tested on Ubuntu 22.04. Minimum: 2 vCPU, 4 GB RAM, 20 GB SSD.

### 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# log out and back in
```

### 2. Clone and configure

```bash
git clone https://github.com/jinujon007/RE_OS.git
cd RE_OS
cp .env.example .env
nano .env  # set DB_PASSWORD and API keys
```

### 3. Start

```bash
docker compose up -d
docker compose ps
```

### 4. Firewall

Only expose port 8050 if you need remote dashboard access. All other ports (5432, 6379, 11434) should remain closed to the internet.

```bash
# UFW example — allow only SSH + dashboard
ufw allow 22
ufw allow 8050
ufw enable
```

For production use, put Nginx in front of port 8050 with HTTPS:

```nginx
server {
    listen 443 ssl;
    server_name re-os.yourcompany.com;

    location / {
        proxy_pass http://localhost:8050;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Grafana Remote Access

Grafana runs on port 3000 (internal only by default). To expose:

```yaml
# docker-compose.yml — uncomment ports under grafana:
ports:
  - "3000:3000"
```

For production, put Grafana behind the same Nginx reverse proxy.

**Security note:** the default Grafana config uses anonymous admin access (fine for local use). For remote access, set:
```yaml
GF_AUTH_ANONYMOUS_ENABLED: "false"
GF_SECURITY_ADMIN_PASSWORD: "your-secure-password"
```

---

## Scheduled Scraping

The scheduler container runs automatically. Default schedule:

| Job | Time (IST) | What |
|-----|-----------|------|
| RERA refresh | 02:00 | Scrape + store all TARGET_MARKETS |
| Market snapshot | 06:00 | Daily rollup to market_snapshots |
| Embedding index | 04:30 | Index new intel reports into ChromaDB |
| Sentiment scoring | 05:00 | Score unscored news_articles |
| Memory decay | Monday 03:00 | Decay agent memory confidence |

To change schedules: edit `config/scheduler.py` and restart:
```bash
docker compose restart scheduler
```

---

## Backup

Postgres data lives in the `postgres_data` Docker volume. Back it up with:

```bash
docker compose exec postgres pg_dump -U re_os_user re_os | gzip > backup_$(date +%Y%m%d).sql.gz
```

Restore:
```bash
gunzip -c backup_20260602.sql.gz | docker compose exec -T postgres psql -U re_os_user re_os
```

Schedule daily backups with cron:
```cron
0 1 * * * cd /path/to/RE_OS && docker compose exec postgres pg_dump -U re_os_user re_os | gzip > /backups/re_os_$(date +\%Y\%m\%d).sql.gz
```

---

## Environment Variable Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | **Yes** | PostgreSQL password |
| `GROQ_API_KEY` | Recommended | CEO primary LLM (free tier) |
| `CEREBRAS_API_KEY` | Optional | Analyst + Scraper (1M tok/day free) |
| `GEMINI_API_KEY` | Optional | CEO fallback + Scraper LIGHT fallback |
| `NVIDIA_API_KEY` | Optional | 405B model, 40 req/min free |
| `OPENROUTER_API_KEY` | Optional | Last-resort fallback |
| `SAMBANOVA_API_KEY` | Optional | 20M tok/day, 20 RPM |
| `CLOUDFLARE_API_KEY` | Optional | Tier 5 fallback |
| `CLOUDFLARE_ACCOUNT_ID` | Optional | Required with Cloudflare key |
| `HF_API_KEY` | Optional | FinBERT sentiment (always-warm free) |
| `JINA_API_KEY` | Optional | 1M free embedding tokens |
| `DASHBOARD_API_KEY` | Recommended | Protects mutation endpoints |
| `TARGET_MARKETS` | Optional | `Yelahanka,Devanahalli,Hebbal` |
| `DISCORD_WEBHOOK_*` | Optional | One per market + types |
| `LOG_LEVEL` | Optional | `INFO` / `DEBUG` / `WARNING` |
| `CHROMA_DB_PATH` | Internal | `/app/data/chroma` (set by compose) |

---

## Upgrading

```bash
git pull
docker compose build agents
docker compose up -d agents scheduler
docker compose exec agents alembic upgrade head
```

The `alembic upgrade head` is also run automatically on container start — so for non-schema changes, `docker compose up -d` is sufficient.

---

## Troubleshooting

### Container won't start
```bash
docker compose logs <container_name> --tail 50
```

### Database schema out of sync
```bash
docker compose exec agents alembic upgrade head
```

### LLM routing errors
All providers have been rate-limited. Check:
```bash
docker compose exec agents python utils/status.py
```
Then either wait for quota reset or pull Ollama: `docker compose exec ollama ollama pull llama3.1:8b`

### Reset everything (nuclear option)
```bash
docker compose down -v   # destroys ALL data
docker compose up -d
```
