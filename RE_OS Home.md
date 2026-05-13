# RE_OS — Real Estate Intelligence OS

> Automated market intelligence for LLS (Land & Life Space) | North Bengaluru Corridor

---

## 🏠 What This Is

RE_OS is a multi-agent AI system that automatically scrapes, structures, and analyzes Bengaluru real estate market data from RERA Karnataka, listing portals, and Kaveri registrations — and delivers actionable intelligence directly to you.

---

## 📊 Intelligence Reports

Reports are saved here after each run:
- [[outputs/yelahanka/]] — Yelahanka micro-market reports
- [[outputs/devanahalli/]] — Devanahalli micro-market reports  
- [[outputs/hebbal/]] — Hebbal micro-market reports

---

## 🎯 Target Markets

| Market | Corridor | Priority |
|--------|----------|----------|
| Yelahanka | North | Active |
| Devanahalli | Airport | Active |
| Hebbal | NH-44 | Active |
| Jakkur | North | Queued |
| Thanisandra | North | Queued |

---

## 🤖 Agent Architecture

| Agent | Role | LLM |
|-------|------|-----|
| CEO Agent | Orchestration + final synthesis | Groq 70B |
| Scraper Agent | RERA + listings data pull | Ollama 8B |
| Parser Agent | Raw data → clean JSON | Ollama 8B |
| Organizer Agent | DB writes + deduplication | Ollama 8B |
| Analyst Agent | Market intelligence brief | Groq Scout 128k |

**Fallback chain:** Groq → NVIDIA 405B → OpenRouter → Ollama

---

## 🔧 System Status

Check live status:
```bash
docker compose ps
docker compose exec agents python -c "from config.llm_router import get_router_status; import json; print(json.dumps(get_router_status(), indent=2))"
```

---

## 📁 Reference Docs

- [[MODELS]] — All free models across every provider with rate limits
- [[SETUP]] — Initial setup guide
- [[BEGINNER_GUIDE]] — Docker and system basics

---

## 🚀 Run Intelligence Scan

```bash
# Single market (fastest for testing)
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka

# All 3 markets
docker compose exec agents python crews/market_intel_crew.py

# Report from existing DB data (no scraping)
docker compose exec agents python crews/market_intel_crew.py --report-only Yelahanka
```

---

## 📅 Last Run
*Update this after each run*

| Date | Market | Projects Found | Report |
|------|--------|---------------|--------|
| — | — | — | — |

---

*RE_OS · LLS Business Development · Bengaluru, Karnataka*
