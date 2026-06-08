import os
from datetime import datetime
from loguru import logger
from utils.weekly_digest import WeeklyDigestResult
from utils.monthly_digest import MonthlyDigestResult

OBSIDIAN_SYNC_PATH = os.environ.get("OBSIDIAN_SYNC_PATH", "/app/obsidian_sync")

_DIGEST_TEMPLATES = {
    "weekly": {
        "title": "Weekly Market Digest",
        "result_type": WeeklyDigestResult,
        "fields": [
            ("PSF Delta", lambda r: f"{r.psf_delta_pct:+.2f}% ({r.psf_direction})"),
            ("New RERA Registrations", lambda r: str(r.new_rera_count)),
            ("Competitor Launches", lambda r: str(len(r.competitor_launches))),
            ("Distressed Developers", lambda r: str(len(r.distressed_developers))),
        ],
        "list_launches": True,
        "list_distressed": True,
        "show_top_opp": "single",
        "show_synthesis": False,
    },
    "monthly": {
        "title": "Monthly Market Digest",
        "result_type": MonthlyDigestResult,
        "fields": [
            ("PSF MoM", lambda r: f"{r.psf_mom_pct:+.2f}%"),
            ("Absorption Trend", lambda r: r.absorption_trend),
            ("Pipeline Supply Added", lambda r: f"{r.pipeline_supply_added} units"),
            ("GCC Events", lambda r: str(r.gcc_events_count)),
            ("Govt Policy Events", lambda r: str(r.govt_policy_events_count)),
        ],
        "list_launches": False,
        "list_distressed": False,
        "show_top_opp": "multiple",
        "show_synthesis": True,
    },
}


def _write_digest(results: list, digest_type: str, date_str: str | None = None) -> str:
    if not results:
        logger.info(f"[ObsidianExport] No results — skipping {digest_type} export")
        return ""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    if not os.path.isdir(OBSIDIAN_SYNC_PATH):
        logger.info(f"[ObsidianExport] Sync path not mounted — skipping {digest_type} export")
        return ""

    tmpl = _DIGEST_TEMPLATES.get(digest_type)
    if not tmpl:
        logger.warning(f"[ObsidianExport] Unknown digest type: {digest_type}")
        return ""

    expected_type = tmpl["result_type"]
    for r in results:
        if not isinstance(r, expected_type):
            logger.warning(f"[ObsidianExport] Expected {expected_type.__name__}, got {type(r).__name__} — skipping")
            return ""

    lines = [
        "---",
        "type: wiki",
        f"date: {date_str}",
        "area: lls",
        "status: active",
        "ai_generated: true",
        "confidence: 0.75",
        "sources: 3",
        f"last_confirmed: {date_str}",
        "---",
        "",
        f"# {tmpl['title']} — {date_str}",
        "",
    ]
    for r in results:
        lines.append(f"## {r.market}")
        lines.append("")
        for label, fn in tmpl["fields"]:
            lines.append(f"**{label}:** {fn(r)}")
        if tmpl["list_launches"]:
            for c in r.competitor_launches[:5]:
                lines.append(f"- {c['developer_name']} — {c['project_name']} (Grade {c['grade']}, {c['units']} units)")
        if tmpl["list_distressed"]:
            for d in r.distressed_developers[:5]:
                lines.append(f"- {d['developer_name']} (score: {d['distress_score']:.2f})")
        if tmpl["show_top_opp"] == "single":
            if r.top_opportunity:
                t = r.top_opportunity
                lines.append(f"**Top Opportunity:** {t['survey_no']} — composite score {t['composite_score']:.4f}")
        elif tmpl["show_top_opp"] == "multiple":
            for o in r.top_opportunities[:3]:
                lines.append(f"**Top Opp:** {o['survey_no']} — composite {o['composite_score']:.4f}")
        if tmpl["show_synthesis"]:
            if r.llm_synthesis:
                lines.append(f"**Synthesis:** {r.llm_synthesis}")
        lines.append("")

    content = "\n".join(lines)
    filename = f"(AI) {tmpl['title']} {date_str}.md"
    filepath = os.path.join(OBSIDIAN_SYNC_PATH, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[ObsidianExport] Written {digest_type} digest to {filepath}")
        return filepath
    except Exception as exc:
        logger.warning(f"[ObsidianExport] Failed to write {digest_type} digest: {exc}")
        return ""


class ObsidianExport:
    @staticmethod
    def write_weekly(results: list, date_str: str | None = None) -> str:
        return _write_digest(results, "weekly", date_str)

    @staticmethod
    def write_monthly(results: list, date_str: str | None = None) -> str:
        return _write_digest(results, "monthly", date_str)
