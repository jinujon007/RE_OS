"""
RE_OS — RERA Record Validator
──────────────────────────────
Validates scraped RERA records before any DB write.
Runs between the scraper and the organizer — nothing bad ever reaches the DB.

Rules:
  - rera_number must match PRM/KA/ or PRM/ pattern
  - project_name must be non-empty
  - total_units must be a non-negative integer
  - developer_name must be non-empty

Usage:
    valid, invalid, report = validate_rera_records(raw_projects)
"""

import re
from loguru import logger

RERA_NUMBER_RE = re.compile(r'^PR[A-Z]*/KA/', re.IGNORECASE)
RERA_NUMBER_LOOSE_RE = re.compile(r'^PRM/', re.IGNORECASE)


def validate_rera_records(records: list) -> tuple:
    """
    Validate a list of raw RERA project dicts.

    Returns:
        valid   — list of records that passed all checks
        invalid — list of records with _validation_errors key added
        report  — dict with counts and error summary
    """
    if not records:
        return [], [], {"total": 0, "valid": 0, "invalid": 0, "error_summary": []}

    valid = []
    invalid = []

    for raw in records:
        if not isinstance(raw, dict):
            invalid.append({"_raw": raw, "_validation_errors": ["not a dict"]})
            continue

        errors = _check_record(raw)

        if errors:
            flagged = dict(raw)
            flagged["_validation_errors"] = errors
            invalid.append(flagged)
            logger.warning(
                f"[Validator] INVALID {raw.get('rera_number', 'NO_RERA')}: {errors}"
            )
        else:
            r_out = dict(raw)
            if str(raw.get("data_source", "")).lower() == "seed_estimated":
                r_out["project_name"] = f"[ESTIMATED] {raw.get('project_name', '')}"
            valid.append(r_out)

    error_summary = []
    for r in invalid:
        for e in r.get("_validation_errors", []):
            error_summary.append(f"{r.get('rera_number', '?')}: {e}")

    report = {
        "total":   len(records),
        "valid":   len(valid),
        "invalid": len(invalid),
        "pass_rate_pct": round(len(valid) / len(records) * 100, 1) if records else 0,
        "error_summary": error_summary[:20],  # cap for log readability
    }

    logger.info(
        f"[Validator] {report['valid']}/{report['total']} valid "
        f"({report['pass_rate_pct']}% pass rate)"
    )
    return valid, invalid, report


def _check_record(r: dict) -> list:
    errors = []

    # ── RERA number ───────────────────────────────────────────────
    rera_num = str(r.get("rera_number", "")).strip()
    if not rera_num:
        errors.append("missing rera_number")
    elif not (RERA_NUMBER_RE.match(rera_num) or RERA_NUMBER_LOOSE_RE.match(rera_num)):
        errors.append(f"bad rera_number format: '{rera_num}'")

    # ── Project name ──────────────────────────────────────────────
    name = str(r.get("project_name", "")).strip()
    if not name or name.lower() in {"n/a", "na", "null", "none", "-"}:
        errors.append("empty or placeholder project_name")

    # ── Developer ─────────────────────────────────────────────────
    dev = str(r.get("developer_name", "")).strip()
    if not dev or dev.lower() in {"n/a", "na", "unknown developer", "null", ""}:
        errors.append("empty developer_name")

    # ── Units ─────────────────────────────────────────────────────
    total = r.get("total_units", None)
    try:
        total_int = int(total)
        if total_int < 0:
            errors.append(f"negative total_units: {total_int}")
    except (TypeError, ValueError):
        errors.append(f"non-integer total_units: '{total}'")

    return errors


def validate_and_log(records: list, market_name: str) -> tuple:
    """Convenience wrapper — logs context-aware summary."""
    valid, invalid, report = validate_rera_records(records)
    if invalid:
        logger.warning(
            f"[Validator] {market_name}: {len(invalid)} records rejected. "
            f"First reason: {invalid[0].get('_validation_errors', ['?'])[0]}"
        )
    return valid, invalid, report
