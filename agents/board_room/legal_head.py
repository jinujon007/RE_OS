"""
RE_OS — Legal Head Agent (Phase 12 — Legal Department)
Data-grounded RERA compliance, zone risk, and encumbrance analysis.
"""
import json
from loguru import logger
from crewai.tools import BaseTool
from utils.rera_compliance_checker import check_developer_compliance
from utils.zone_risk_checker import check_zone_risk
from utils.kaveri_encumbrance import check_encumbrance


class RERAComplianceTool(BaseTool):
    name: str = "rera_compliance_check"
    description: str = (
        "Check a developer's RERA Karnataka record from DB. "
        "JSON input: {'developer_name': str, 'market'?: str}. "
        "Returns projects, delays, signal (CLEAN|WATCH|RISK). "
        "Returns UNKNOWN + empty stats if developer not in DB (valid result, not an error)."
    )
    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON"})
        try:
            dev_name = str(params.get("developer_name", "")).strip()
            market = str(params.get("market", "")).strip() or None
            r = check_developer_compliance(dev_name, market=market)
            logger.info("[RERAComplianceTool] developer=%s market=%s signal=%s",
                        r.developer_name, market, r.compliance_signal)
            return json.dumps({
                "developer": r.developer_name,
                "market": r.market,
                "total_projects": r.total_projects,
                "active_projects": r.active_projects,
                "completed_projects": r.completed_projects,
                "delayed": r.delayed_projects,
                "avg_delay_months": r.avg_delay_months,
                "signal": r.compliance_signal,
                "inactive_anomalies": r.inactive_anomalies,
                "notes": r.notes,
            }, indent=2)
        except Exception as e:
            logger.warning("[RERAComplianceTool] error: %s", e)
            return json.dumps({"error": str(e)})


class ZoneRiskTool(BaseTool):
    name: str = "zone_risk_check"
    description: str = (
        "Check zone rules + overlay constraints for a market. "
        "JSON input: {'market': str, 'zone'?: 'R1'|'R2'|'C1'}. "
        "Returns FAR, height limit, setbacks, overlay risks, risk level (LOW|MEDIUM|HIGH|UNKNOWN)."
    )
    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON"})
        try:
            market = str(params.get("market", "")).strip()
            zone = str(params.get("zone", "R2")).strip()
            r = check_zone_risk(market, zone)
            logger.info("[ZoneRiskTool] market=%s zone=%s risk_level=%s overlays=%d",
                        r.market, r.zone, r.risk_level, len(r.overlay_risks))
            return json.dumps({
                "market": r.market, "zone": r.zone,
                "far": r.far,
                "max_height_m": r.max_height_m,
                "ground_coverage_pct": r.ground_coverage_pct,
                "setback_front_m": r.setback_front_m,
                "setback_side_m": r.setback_side_m,
                "overlay_risks": r.overlay_risks,
                "risk_level": r.risk_level,
            }, indent=2)
        except Exception as e:
            logger.warning("[ZoneRiskTool] error: %s", e)
            return json.dumps({"error": str(e)})


class EncumbranceCheckTool(BaseTool):
    name: str = "encumbrance_check"
    description: str = (
        "Check encumbrance via Kaveri data for a market. "
        "JSON input: {'market': str, 'survey_no'?: str}. "
        "Returns avg guidance value PSF, transaction count, gap %, risk flags. "
        "DB-first, Kaveri portal fallback if DB empty."
    )
    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON"})
        try:
            market = str(params.get("market", "")).strip()
            survey = str(params.get("survey_no", "")).strip() or None
            r = check_encumbrance(market, survey_no=survey)
            logger.info("[EncumbranceCheckTool] market=%s data_source=%s regs=%d gap=%s",
                        r.market, r.data_source, r.registration_count_180d, r.guidance_gap_pct)
            return json.dumps({
                "market": r.market,
                "survey_no": r.survey_no,
                "avg_guidance_value_psf": r.avg_guidance_value_psf,
                "registration_count_180d": r.registration_count_180d,
                "avg_transaction_psf": r.avg_transaction_psf,
                "guidance_gap_pct": r.guidance_gap_pct,
                "data_source": r.data_source,
                "risk_flags": r.risk_flags,
            }, indent=2)
        except Exception as e:
            logger.warning("[EncumbranceCheckTool] error: %s", e)
            return json.dumps({"error": str(e)})


class DocumentParseTool(BaseTool):
    name: str = "parse_document"
    description: str = (
        "Parse a legal document (PDF, DOCX, XLSX, PPTX, HTML) and return its text as markdown. "
        "JSON input: {'file_path': str} — absolute or relative path to the file. "
        "Use for EC certificates, RERA approval PDFs, sale deeds, layout approval letters. "
        "Returns: {'content': str, 'char_count': int} or {'error': str}."
    )
    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON"})
        try:
            file_path = str(params.get("file_path", "")).strip()
            from utils.kaveri_encumbrance import parse_document
            text = parse_document(file_path)
            logger.info("[DocumentParseTool] file=%s chars=%d", file_path, len(text))
            return json.dumps({"content": text, "char_count": len(text)}, indent=2)
        except Exception as e:
            logger.warning("[DocumentParseTool] error: %s", e)
            return json.dumps({"error": str(e)})


def build_legal_head_agent():
    from crewai import Agent
    from config.llm_router import get_analysis_llm

    return Agent(
        role="Legal Head",
        goal=(
            "Identify legal, regulatory, and title risks that could block or delay this project. "
            "You call rera_compliance_check for any named developer, zone_risk_check for any "
            "named market, encumbrance_check for market-level guidance value trends, and "
            "parse_document if a PDF or document file path is provided (EC cert, RERA approval, "
            "sale deed). Your response is grounded in DB data and document content, not general knowledge."
        ),
        backstory=(
            "You are the Legal Head at LLS. Your lens: RERA Karnataka registration compliance, "
            "BDA/BBMP layout approval status, encumbrance search, title chain clarity, "
            "conversion from agricultural to residential use (Section 95 of KLR Act), "
            "and proximity to regulatory overlays (airport zone, green belt, lake buffer, "
            "high-tension line, rajakaluve). "
            "You respond with: CLEAR / RISK / BLOCKED. You name every unresolved legal item "
            "with its Karnataka-specific statute or regulatory body. "
            "You call rera_compliance_check for any named developer, zone_risk_check "
            "for any named market, encumbrance_check for market-level Kaveri data, and "
            "parse_document for any PDF or document file the user provides — EC certificates, "
            "RERA approval letters, sale deeds, layout approval orders. "
            "Your response is grounded in DB data and document content, not general knowledge."
        ),
        tools=[RERAComplianceTool(), ZoneRiskTool(), EncumbranceCheckTool(), DocumentParseTool()],
        llm=get_analysis_llm(),
        max_iter=3,
        verbose=False,
        allow_delegation=False,
    )


if __name__ == "__main__":
    agent = build_legal_head_agent()
    print(f"Legal Head Agent created: {agent.role}")
    print(f"Tools: {[t.name for t in agent.tools]}")
    print(f"max_iter: {agent.max_iter}")
