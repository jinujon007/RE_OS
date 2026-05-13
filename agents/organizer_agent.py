"""
RE_OS — Organizer Agent
────────────────────────
The database keeper. Takes clean parsed data and writes it to PostgreSQL.
Handles deduplication, upserts, relationship linking, and data integrity.
Uses Ollama — no heavy reasoning needed here, just careful execution.
"""

from crewai import Agent
from crewai.tools import BaseTool
from sqlalchemy import create_engine, text
from loguru import logger
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DATABASE_URL, GRADE_A_DEVELOPERS, GRADE_A_MIN_UNITS, GRADE_B_MIN_UNITS
from config.llm_router import get_light_llm


def get_engine():
    return create_engine(DATABASE_URL)


class UpsertRERAProjectTool(BaseTool):
    name: str = "upsert_rera_project"
    description: str = (
        "Inserts or updates a RERA project record in the database. "
        "Handles deduplication by RERA number. Links developer and micro-market. "
        "Input: JSON string of a parsed RERA project record. "
        "Output: status message with record ID."
    )

    def _run(self, project_json: str) -> str:
        try:
            project = json.loads(project_json)
            engine = get_engine()

            with engine.begin() as conn:
                # 1. Upsert developer
                developer_id = self._upsert_developer(conn, project)

                # 2. Get micro-market ID
                market_id = self._get_market_id(conn, project)

                # 3. Determine project grade for developer
                self._update_developer_grade(conn, developer_id, project)

                # 4. Upsert RERA project
                result = conn.execute(text("""
                    INSERT INTO rera_projects (
                        rera_number, project_name, developer_id, micro_market_id,
                        address, district, taluk, locality,
                        project_type, project_status,
                        total_units, sold_units, unsold_units,
                        possession_date, registration_date,
                        raw_data, last_scraped_at
                    ) VALUES (
                        :rera_number, :project_name, :developer_id, :market_id,
                        :address, :district, :taluk, :locality,
                        :project_type, :project_status,
                        :total_units, :sold_units, :unsold_units,
                        :possession_date, :registration_date,
                        :raw_data, NOW()
                    )
                    ON CONFLICT (rera_number) DO UPDATE SET
                        project_name = EXCLUDED.project_name,
                        project_status = EXCLUDED.project_status,
                        total_units = EXCLUDED.total_units,
                        sold_units = EXCLUDED.sold_units,
                        unsold_units = EXCLUDED.unsold_units,
                        possession_date = EXCLUDED.possession_date,
                        raw_data = EXCLUDED.raw_data,
                        last_scraped_at = NOW(),
                        updated_at = NOW()
                    RETURNING id
                """), {
                    "rera_number": project.get('rera_number', ''),
                    "project_name": project.get('project_name', ''),
                    "developer_id": developer_id,
                    "market_id": market_id,
                    "address": project.get('address'),
                    "district": project.get('district'),
                    "taluk": project.get('taluk'),
                    "locality": project.get('locality'),
                    "project_type": project.get('project_type', 'Residential'),
                    "project_status": project.get('project_status'),
                    "total_units": project.get('total_units', 0),
                    "sold_units": project.get('sold_units', 0),
                    "unsold_units": project.get('unsold_units', 0),
                    "possession_date": project.get('possession_date'),
                    "registration_date": project.get('registration_date'),
                    "raw_data": json.dumps(project.get('raw_data', {})),
                })

                row = result.fetchone()
                return json.dumps({"status": "success", "project_id": str(row[0])})

        except Exception as e:
            logger.error(f"Upsert failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    def _upsert_developer(self, conn, project: dict) -> str:
        dev_name = project.get('developer_name', 'Unknown Developer')
        dev_name_norm = dev_name.lower().strip()

        result = conn.execute(text("""
            INSERT INTO developers (name, name_normalized)
            VALUES (:name, :name_normalized)
            ON CONFLICT DO NOTHING
            RETURNING id
        """), {"name": dev_name, "name_normalized": dev_name_norm})

        row = result.fetchone()
        if row:
            return str(row[0])

        # Already exists — fetch it
        result = conn.execute(text(
            "SELECT id FROM developers WHERE name_normalized = :n"
        ), {"n": dev_name_norm})
        row = result.fetchone()
        return str(row[0]) if row else None

    def _get_market_id(self, conn, project: dict) -> str:
        locality = project.get('locality', '')
        taluk = project.get('taluk', '')

        # Try to match by locality keywords
        from config.settings import MARKET_RERA_KEYWORDS
        for market_name, keywords in MARKET_RERA_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in locality.lower() or kw.lower() in taluk.lower():
                    result = conn.execute(text(
                        "SELECT id FROM micro_markets WHERE name = :name"
                    ), {"name": market_name})
                    row = result.fetchone()
                    if row:
                        return str(row[0])
        return None

    def _update_developer_grade(self, conn, developer_id: str, project: dict):
        if not developer_id:
            return

        dev_name = project.get('developer_name', '').lower()
        total_units = project.get('total_units', 0)

        # Determine grade
        grade = 'C'
        for known_dev in GRADE_A_DEVELOPERS:
            if known_dev in dev_name:
                grade = 'A'
                break
        if grade == 'C' and total_units >= GRADE_A_MIN_UNITS:
            grade = 'A'
        elif grade == 'C' and total_units >= GRADE_B_MIN_UNITS:
            grade = 'B'

        conn.execute(text("""
            UPDATE developers SET grade = :grade WHERE id = :id
        """), {"grade": grade, "id": developer_id})


class LogAgentRunTool(BaseTool):
    name: str = "log_agent_run"
    description: str = (
        "Logs the result of an agent scraping run to the agent_runs table. "
        "Input: JSON with agent_name, task_type, micro_market, status, counts."
    )

    def _run(self, log_json: str) -> str:
        try:
            log = json.loads(log_json)
            engine = get_engine()
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO agent_runs
                    (agent_name, task_type, micro_market, status,
                     records_scraped, records_inserted, records_updated, error_message, completed_at)
                    VALUES
                    (:agent_name, :task_type, :micro_market, :status,
                     :scraped, :inserted, :updated, :error, NOW())
                """), {
                    "agent_name": log.get('agent_name', 'unknown'),
                    "task_type": log.get('task_type', 'unknown'),
                    "micro_market": log.get('micro_market', ''),
                    "status": log.get('status', 'completed'),
                    "scraped": log.get('records_scraped', 0),
                    "inserted": log.get('records_inserted', 0),
                    "updated": log.get('records_updated', 0),
                    "error": log.get('error_message'),
                })
            return json.dumps({"status": "logged"})
        except Exception as e:
            return json.dumps({"status": "log_error", "message": str(e)})


def create_organizer_agent() -> Agent:
    return Agent(
        role="Database Manager and Data Integrity Specialist",
        goal=(
            "Maintain a clean, accurate, deduplicated RE_OS database. "
            "Every record that enters must be valid. Every update must be tracked. "
            "No duplicates. No orphaned records. No missing relationships."
        ),
        backstory=(
            "You are a meticulous database administrator who has managed large "
            "real estate data systems. You understand upserts, conflict resolution, "
            "and the importance of data lineage. "
            "You never lose data. You never create duplicates. "
            "You log every run so the system always knows what it knows and when it learned it. "
            "You are the guardian of RE_OS data quality."
        ),
        tools=[
            UpsertRERAProjectTool(),
            LogAgentRunTool(),
        ],
        llm=get_light_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=15,
    )
