"""Title risk checklist auto-populated from DB for a given parcel."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from loguru import logger

__all__ = ["TitleRiskChecklist", "TitleRiskResult"]


@dataclass
class TitleRiskResult:
    survey_no: str
    market: str
    khata_status: str = "UNKNOWN"
    ec_check: str = "UNKNOWN"
    dc_conversion: str = "UNKNOWN"
    rera_registration: str = "UNKNOWN"
    overall_risk: str = "UNKNOWN"
    details: dict = field(default_factory=dict)
    collected_at: str = ""

    def __str__(self) -> str:
        return (
            f"[TitleRisk:{self.market}/{self.survey_no}] "
            f"overall={self.overall_risk} "
            f"khata={self.khata_status} ec={self.ec_check} "
            f"dc={self.dc_conversion} rera={self.rera_registration}"
        )


class TitleRiskChecklist:
    _TABLE_EXISTENCE_CACHE: dict[str, bool] = {}

    @classmethod
    def _table_exists(cls, conn, table_name: str) -> bool:
        if table_name in cls._TABLE_EXISTENCE_CACHE:
            return cls._TABLE_EXISTENCE_CACHE[table_name]
        try:
            from sqlalchemy import text
            row = conn.execute(
                text("SELECT to_regclass(:tn)"),
                {"tn": table_name},
            ).scalar()
            exists = row is not None
            cls._TABLE_EXISTENCE_CACHE[table_name] = exists
            return exists
        except Exception:
            return False

    @staticmethod
    def _normalize_survey(survey_no: str) -> str:
        return (survey_no or "").strip().upper()[:100]

    @classmethod
    def from_parcel(cls, survey_no: str, market: str, engine=None) -> TitleRiskResult:
        from sqlalchemy import text

        s = TitleRiskChecklist._normalize_survey(survey_no)
        m = (market or "").strip()[:100]
        result = TitleRiskResult(survey_no=s, market=m)
        result.collected_at = datetime.now(timezone.utc).isoformat()

        if not s or not m:
            result.overall_risk = "UNKNOWN"
            return result

        try:
            if engine is None:
                from utils.db import get_engine
                engine = get_engine()

            with engine.connect() as conn:
                khata_status = "UNKNOWN"
                khata_detail = ""
                if cls._table_exists(conn, "parcel_ownership_chain"):
                    try:
                        row = conn.execute(
                            text("""
                            SELECT govt_acquisition_notice, encumbrance_flag
                            FROM parcel_ownership_chain
                            WHERE survey_no = :sno
                            LIMIT 1
                        """),
                            {"sno": s},
                        ).fetchone()
                        if row:
                            govt_acq = bool(row[0]) if row[0] else False
                            encum = bool(row[1]) if row[1] else False
                            if govt_acq or encum:
                                khata_status = "ALERT"
                                parts = []
                                if govt_acq:
                                    parts.append("govt_acquisition_notice")
                                if encum:
                                    parts.append("encumbrance_flag")
                                khata_detail = f"Flags: {', '.join(parts)}"
                            else:
                                khata_status = "CLEAR"
                                khata_detail = "No acquisition or encumbrance flags"
                        else:
                            khata_status = "UNKNOWN"
                            khata_detail = "No ownership chain found for survey"
                    except Exception as exc:
                        logger.warning("[TitleRisk] khata query failed: {}", exc)
                        khata_status = "UNKNOWN"
                        khata_detail = f"DB error: {exc}"
                else:
                    khata_detail = "Table parcel_ownership_chain not found in schema"
                result.khata_status = khata_status
                result.details["khata_detail"] = khata_detail

                ec_check = "UNKNOWN"
                ec_detail = ""
                if cls._table_exists(conn, "registered_transactions"):
                    try:
                        row = conn.execute(
                            text("""
                            SELECT COUNT(*), MAX(reg_date), MIN(reg_date)
                            FROM registered_transactions
                            WHERE survey_no_raw = :sno
                        """),
                            {"sno": s},
                        ).fetchone()
                        count = int(row[0]) if row and row[0] else 0
                        if count > 0:
                            last_date = row[1]
                            first_date = row[2]
                            ec_detail = (
                                f"{count} deed(s), range: {first_date} → {last_date}"
                            )
                            if count == 1 and last_date and (
                                datetime.now(timezone.utc).date() - last_date
                            ).days < 365:
                                ec_check = "FLAG"
                                ec_detail += " — single recent deed, verify exclusive chain"
                            elif count >= 3:
                                ec_check = "CLEAR"
                                ec_detail += " — multiple deeds, chain traceable"
                            else:
                                ec_check = "FLAG"
                                ec_detail += " — limited history, recommend title search"
                        else:
                            ec_check = "CLEAR"
                            ec_detail = "No deeds on record"
                    except Exception as exc:
                        logger.warning("[TitleRisk] ec query failed: {}", exc)
                        ec_check = "UNKNOWN"
                        ec_detail = f"DB error: {exc}"
                else:
                    ec_detail = "Table registered_transactions not found in schema"
                result.ec_check = ec_check
                result.details["ec_detail"] = ec_detail

                dc_conversion = "UNKNOWN"
                dc_detail = ""
                if cls._table_exists(conn, "dc_conversions"):
                    try:
                        row = conn.execute(
                            text("""
                            SELECT MAX(date), from_use, to_use
                            FROM dc_conversions
                            WHERE survey_no = :sno
                            GROUP BY from_use, to_use
                            ORDER BY MAX(date) DESC
                            LIMIT 1
                        """),
                            {"sno": s},
                        ).fetchone()
                        if row:
                            dc_date = row[0]
                            dc_conversion = f"DC granted on {dc_date}"
                            dc_detail = f"From: {row[1]} → To: {row[2]} on {dc_date}"
                        else:
                            dc_conversion = "NONE"
                            dc_detail = "No DC conversion records found"
                    except Exception as exc:
                        logger.warning("[TitleRisk] dc query failed: {}", exc)
                        dc_conversion = "UNKNOWN"
                        dc_detail = f"DB error: {exc}"
                else:
                    dc_detail = "Table dc_conversions not found in schema"
                result.dc_conversion = dc_conversion
                result.details["dc_detail"] = dc_detail

                rera_reg = "UNKNOWN"
                rera_detail = ""
                if cls._table_exists(conn, "rera_projects"):
                    try:
                        row = conn.execute(
                            text("""
                            SELECT project_name
                            FROM rera_projects
                            WHERE survey_no = :sno
                            LIMIT 1
                        """),
                            {"sno": s},
                        ).fetchone()
                        if row:
                            rera_reg = f"RERA project: {row[0]}"
                            rera_detail = f"Registered project '{row[0]}' linked to survey"
                        else:
                            rera_reg = "NONE"
                            rera_detail = "No RERA project linked to this survey"
                    except Exception as exc:
                        logger.warning("[TitleRisk] rera query failed: {}", exc)
                        rera_reg = "UNKNOWN"
                        rera_detail = f"DB error: {exc}"
                else:
                    rera_detail = "Table rera_projects not found in schema"
                result.rera_registration = rera_reg
                result.details["rera_detail"] = rera_detail

            flags = [result.khata_status, result.ec_check]
            risks = sum(1 for f in flags if f == "ALERT" or f == "FLAG")
            unknowns = sum(1 for f in flags if f == "UNKNOWN")
            if result.khata_status == "ALERT":
                result.overall_risk = "HIGH"
            elif risks >= 2:
                result.overall_risk = "HIGH"
            elif risks == 1:
                result.overall_risk = "MEDIUM"
            elif unknowns >= 2:
                result.overall_risk = "MEDIUM"
            else:
                result.overall_risk = "LOW"

        except Exception as exc:
            logger.warning("[TitleRisk] from_parcel({}, {}) failed: {}", s, m, exc)
            result.overall_risk = "UNKNOWN"
            result.details["error"] = str(exc)

        return result
