# Contributing to RE_OS

Thank you for your interest. RE_OS is an active project — contributions that extend its intelligence coverage, improve pipeline reliability, or add new markets are welcome.

---

## Before You Start

1. Read [VISION.md](../VISION.md) — the 14-phase roadmap describes everything planned. Most meaningful contributions fit into an existing phase.
2. Read [CLAUDE.md](../CLAUDE.md) — understand the agent architecture, LLM routing, and 3-stage pipeline before touching agent code.
3. Read [HOW_TO_RUN.md](../HOW_TO_RUN.md) — get the stack running locally before writing code.

---

## What We Welcome

- **New data sources** — new scout scrapers (additional RERA states, registration portals, listing sites)
- **Market expansions** — extending coverage to new Indian cities or micro-markets
- **Pipeline reliability** — better error handling, retry logic, checkpoint improvements
- **Analytics views** — new PostgreSQL views or metrics that surface better signals
- **LLM router improvements** — new free provider integrations, better fallback logic
- **Documentation** — clearer setup guides, troubleshooting, architecture explanations
- **Bug fixes** — especially scraper failures, DB upsert conflicts, LLM routing errors

## What We Don't Accept

- New dependencies without discussion (keep the stack lean)
- Architecture changes that bypass the CEO → Scraper/Analyst → DB flow
- Code that commits real estate data or API keys
- Breaking schema changes without a migration path

---

## Development Setup

```bash
git clone https://github.com/jinujon007/RE_OS.git
cd RE_OS
cp .env.example .env
# Add at least GROQ_API_KEY to .env
docker compose up -d
docker compose exec ollama ollama pull llama3.1:8b
```

Verify the stack is healthy:
```bash
docker compose ps
docker compose exec agents python utils/status.py
```

---

## Making Changes

### Coding standards

- Python 3.11. Follow existing module patterns — agents extend CrewAI `Agent`, scrapers return structured dicts.
- No hardcoded API keys anywhere. All config via `.env` → `config/settings.py`.
- New scrapers must handle zero-result gracefully — return `[]` or fallback sample, never raise.
- New DB tables need entries in `database/schema.sql`. UUID PKs. UPSERT-safe (no ON CONFLICT errors on re-run).
- Run `ruff check .` before pushing. Fix all errors (E501 line-length warnings are ignored in CI).

### Testing your change

```bash
# End-to-end pipeline test (minimum bar for any agent/scraper change)
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka

# Standalone scraper test
docker compose exec agents python scrapers/<your_scraper>.py --market Yelahanka

# DB state check
docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT * FROM v_market_inventory;"
```

Paste relevant log output in your PR.

---

## Submitting a PR

1. Fork the repo and create a branch: `git checkout -b feat/your-feature-name`
2. Make your changes. Update `CHANGELOG.md`.
3. Push and open a PR against `master`.
4. Fill in the PR template completely — especially the "Testing done" section.

CI runs automatically: ruff lint, Python syntax check, docker-compose validation, schema test. PRs must pass all three before review.

---

## Reporting Bugs

Use the [Bug Report template](https://github.com/jinujon007/RE_OS/issues/new?template=bug_report.yml).

Always include:
```bash
docker compose logs agents --tail 50
docker compose ps
```

The exact error line matters more than your interpretation of it.

---

## Questions

Open a [Discussion](https://github.com/jinujon007/RE_OS/discussions) or file an issue. Response time: best-effort.
