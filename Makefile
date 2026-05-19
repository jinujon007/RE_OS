# Makefile — RE_OS developer shortcuts
# Usage: make <target>
# Requires: Docker Desktop running

.PHONY: up down ps logs rebuild \
        run run-yelahanka run-devanahalli run-hebbal \
        db db-inventory db-projects db-developers \
        lint syntax-check test health \
        ollama-pull clean

# ── STACK ─────────────────────────────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs agents --tail 50 -f

rebuild:
	docker compose build agents && docker compose up -d agents

# ── PIPELINE ──────────────────────────────────────────────────────────────────

run:
	docker compose exec agents python crews/market_intel_crew.py

run-yelahanka:
	docker compose exec agents python crews/market_intel_crew.py --market Yelahanka

run-devanahalli:
	docker compose exec agents python crews/market_intel_crew.py --market Devanahalli

run-hebbal:
	docker compose exec agents python crews/market_intel_crew.py --market Hebbal

# ── DATABASE ──────────────────────────────────────────────────────────────────

db:
	docker compose exec postgres psql -U re_os_user -d re_os

db-inventory:
	docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT * FROM v_market_inventory;"

db-projects:
	docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT * FROM v_active_projects LIMIT 20;"

db-developers:
	docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT * FROM v_developer_scorecard;"

# ── LOCAL LLM ─────────────────────────────────────────────────────────────────

ollama-pull:
	docker compose exec ollama ollama pull llama3.1:8b

# ── QUALITY ───────────────────────────────────────────────────────────────────

lint:
	ruff check .

test:
	pytest tests/ -v --tb=short

syntax-check:
	python -m py_compile \
		agents/ceo_agent.py agents/analyst_agent.py agents/scraper_agent.py \
		config/llm_router.py config/settings.py crews/market_intel_crew.py \
		utils/db_organizer.py utils/validator.py

health:
	docker compose exec agents python utils/status.py

# ── CLEANUP ───────────────────────────────────────────────────────────────────

clean:
	docker compose down -v
