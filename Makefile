# Makefile — RE_OS developer shortcuts
# Usage: make <target>
# Requires: Docker Desktop running

.PHONY: up down ps logs logs-scheduler rebuild \
        run run-yelahanka run-devanahalli run-hebbal \
        board \
        db db-inventory db-projects db-developers db-reset \
        dashboard grafana prometheus \
        lint format syntax-check test test-cov health \
        ollama-pull ci clean migrate

# ── STACK ─────────────────────────────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs agents --tail 50 -f

logs-scheduler:
	docker compose logs scheduler --tail 50 -f

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

# ── BOARD ROOM ────────────────────────────────────────────────────────────────

board:
	@echo "Usage: make board MARKET=Yelahanka PITCH='5-acre R2 site, target ₹6500 PSF'"
	@[ -n "$(MARKET)" ] || (echo "Set MARKET=<market>"; exit 1)
	@[ -n "$(PITCH)" ] || (echo "Set PITCH='<pitch text>'"; exit 1)
	docker compose exec agents python -c "\
	  import requests, json; \
	  r = requests.post('http://localhost:8050/api/board/run', \
	    headers={'X-API-Key': '$(DASHBOARD_API_KEY)'}, \
	    json={'market': '$(MARKET)', 'pitch': '$(PITCH)'}); \
	  print(json.dumps(r.json(), indent=2))"

# ── DASHBOARD & OBSERVABILITY ─────────────────────────────────────────────────

dashboard:
	@echo "Dashboard: http://localhost:8050"
	@docker compose exec agents curl -s http://localhost:8050/api/health | python -m json.tool

grafana:
	@echo "Grafana: http://localhost:3000 (anonymous admin)"
	@docker compose ps grafana

prometheus:
	@echo "Prometheus metrics from agents:"
	@docker compose exec agents curl -s http://localhost:8050/metrics | head -40

# ── DATABASE ──────────────────────────────────────────────────────────────────

db:
	docker compose exec postgres psql -U re_os_user -d re_os

db-inventory:
	docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT * FROM v_market_inventory;"

db-projects:
	docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT * FROM v_active_projects LIMIT 20;"

db-developers:
	docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT * FROM v_developer_scorecard;"

db-reset:
	docker compose down -v && docker compose up -d

# ── LOCAL LLM ─────────────────────────────────────────────────────────────────

ollama-pull:
	docker compose exec ollama ollama pull llama3.1:8b

# ── QUALITY ───────────────────────────────────────────────────────────────────

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .

test:
	pytest tests/ -v --tb=short -m unit

test-cov:
	pytest tests/ -m unit --tb=short --cov=agents --cov=config --cov=crews --cov=scrapers --cov=utils --cov=dashboard --cov-report=term-missing

migrate:
	docker compose exec agents alembic upgrade head

ci: lint test syntax-check

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
