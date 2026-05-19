#!/usr/bin/env python
"""Diagnostic script — deep dive RE_OS system state"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

print("=" * 70)
print("RE_OS DIAGNOSTIC — Deep Dive Report")
print("=" * 70)

# 1. LLM Router check
print("\n[1] LLM ROUTER TIERS")
from config.llm_router import get_heavy_llm, get_analysis_llm, get_light_llm
heavy = get_heavy_llm()
analysis = get_analysis_llm()
light = get_light_llm()
print(f"  HEAVY   (CEO):      {heavy.model} — {heavy.temperature}")
print(f"  ANALYSIS (Analyst): {analysis.model} — max_tokens={analysis.max_tokens}")
print(f"  LIGHT   (Scraper):  {light.model} — max_tokens={light.max_tokens}")

# 2. DB health
print("\n[2] DATABASE SCHEMA & DATA")
from utils.db_organizer import DBOrganizer
db = DBOrganizer()
import sqlalchemy as sa
with db.engine.connect() as conn:
    # Table counts
    tables = ['micro_markets', 'developers', 'rera_projects', 'listings',
              'kaveri_registrations', 'guidance_values', 'agent_runs']
    print("  Table counts:")
    for t in tables:
        cnt = conn.execute(sa.text(f'SELECT COUNT(*) FROM {t}')).scalar()
        print(f"    {t}: {cnt}")

    # Orphaned rera_projects (no micro_market_id)
    orphaned = conn.execute(sa.text(
        "SELECT COUNT(*) FROM rera_projects WHERE micro_market_id IS NULL"
    )).scalar()
    print(f"  Orphaned rera_projects (NULL micro_market_id): {orphaned}")

    # Market brief snapshot
    print("\n  v_market_brief:")
    rows = conn.execute(sa.text(
        "SELECT micro_market, total_projects, avg_min_psf, avg_max_psf, avg_absorption_pct "
        "FROM v_market_brief"
    )).fetchall()
    for row in rows:
        psf_min = f"{row.avg_min_psf:.0f}" if row.avg_min_psf else "—"
        psf_max = f"{row.avg_max_psf:.0f}" if row.avg_max_psf else "—"
        absorption = f"{row.avg_absorption_pct:.1f}%" if row.avg_absorption_pct else "—"
        print(f"    {row.micro_market}: {row.total_projects} projects, "
              f"PSF {psf_min}-{psf_max}, absorption {absorption}")

# 3. Check which scout tools are registered
print("\n[3] SCOUT TOOL REGISTRATION")
from agents.scraper_agent import create_scraper_agent
agent = create_scraper_agent()
tool_names = [t.name for t in agent.tools]
print(f"  Scraper agent tools ({len(tool_names)}):")
for name in tool_names:
    print(f"    - {name}")

# 4. Crew Stage 1 task definitions (are scouts wired?)
print("\n[4] CREW STAGE 1 TASKS")
from crews.market_intel_crew import _build_data_crew
data_crew = _build_data_crew("Yelahanka")
print(f"  Data crew tasks ({len(data_crew.tasks)}):")
for t in data_crew.tasks:
    print(f"    - {t.description[:80]}...")

# 5. Checkpoint file locations
print("\n[5] LAST CHECKPOINTS")
import glob
import json
ckpt_dir = "outputs/Yelahanka"
if os.path.exists(ckpt_dir):
    ckpts = sorted(glob.glob(f"{ckpt_dir}/*.json"), key=os.path.getmtime, reverse=True)[:5]
    print(f"  Latest checkpoints in {ckpt_dir}:")
    for c in ckpts:
        size = os.path.getsize(c)
        print(f"    {os.path.basename(c)} ({size} bytes)")
else:
    print("  No outputs/Yelahanka directory found")

# 6. Recent crew.log tail
print("\n[6] LAST CREW.LOG ENTRIES")
log_path = "logs/crew.log"
if os.path.exists(log_path):
    with open(log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()[-15:]
    print("  Tail:")
    for line in lines:
        line = line.rstrip()
        if line.strip():
            print(f"    {line}")
else:
    print("  logs/crew.log not found")

# 7. Dashboard routes check
print("\n[7] DASHBOARD BACKEND ROUTES")
try:
    from dashboard.app import app
    rules = sorted(str(r) for r in app.url_map.iter_rules())
    print(f"  Flask app routes ({len(rules)}):")
    for r in rules:
        print(f"    {r}")
except Exception as e:
    print(f"  ERROR importing dashboard.app: {e}")

# 8. Requirements — are httpx/price-parser/dateparser present?
print("\n[8] PYTHON REQUIREMENTS")
req_path = "requirements.txt"
if os.path.exists(req_path):
    with open(req_path) as f:
        reqs = [ln.strip() for ln in f if ln.strip() and not ln.startswith('#')]
    needed = ['httpx', 'price-parser', 'dateparser']
    print(f"  requirements.txt ({len(reqs)} packages):")
    for pkg in needed:
        present = any(pkg in r for r in reqs)
        print(f"    {pkg}: {'present' if present else 'MISSING'}")
else:
    print("  requirements.txt not found")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
