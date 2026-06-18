"""
RE_OS — Digest Jobs
────────────────────
Weekly/monthly digest generation, CEO letter, PR brief, and
compliance check functions extracted from monolithic scheduler.py.
"""

from collections.abc import Callable
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine
from config.settings import TARGET_MARKETS


def run_weekly_digest():
    """Weekly digest generation — Monday 04:00 IST (after conflict detection).
    Generates top-5 highest-confidence facts for each market and logs them.
    Sends Discord summary to intel channel. Fact text truncated to 200 chars."""
    try:
        from utils.agent_memory import generate_weekly_digest
        from utils.discord_notifier import send

        for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
            _MAX_FACT_LEN = 200
            facts = generate_weekly_digest(market, max_fact_length=_MAX_FACT_LEN)
            if facts:
                lines = [f"**{market} — Weekly Digest**"]
                for f in facts:
                    lines.append(
                        f"- [{f['agent_id']}] {f['fact']} (conf: {f['confidence']:.1%})"
                    )
                summary = "\n".join(lines)
                logger.info(
                    f"[Scheduler] Weekly digest generated for {market}: {len(facts)} facts"
                )
                try:
                    send("intel", f"📋 Weekly Digest — {market}", summary)
                except Exception as exc:
                    logger.warning(
                        f"[Scheduler] Weekly digest Discord failed for {market}: {exc}"
                    )
            else:
                logger.info(f"[Scheduler] Weekly digest: no facts for {market}")
    except Exception as exc:
        logger.warning(f"[Scheduler] Weekly digest generation failed: {exc}")


def _digest_already_sent(digest_type: str, cooldown_hours: int = 23) -> bool:
    """Check if a digest was already sent within cooldown_hours.
    Uses a dedicated marker alert in the ops channel with title 'intel_digest:{type}'.
    Fails open (returns False) on DB error so alerts are never silently dropped."""
    title = f"intel_digest:{digest_type}"
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id FROM alerts
                    WHERE channel = 'ops'
                      AND title = :title
                      AND created_at > NOW() - (:hrs || ' hours')::interval
                    LIMIT 1
                """),
                {"title": title, "hrs": cooldown_hours},
            ).fetchone()
        return row is not None
    except Exception as exc:
        logger.debug("[Digest-Dedup] Check failed — allowing send: {}", exc)
        return False


def _mark_digest_sent(digest_type: str) -> None:
    """Write a dedup marker alert to ops channel so subsequent runs can detect duplicates."""
    title = f"intel_digest:{digest_type}"
    try:
        from utils.discord_notifier import send as _discord_send

        _discord_send("ops", title, f"Digest marker — {digest_type} sent")
    except Exception as exc:
        logger.debug("[Digest-Dedup] Failed to write marker: {}", exc)


def run_weekly_intel_digest():
    """Monday 01:30 UTC = 07:00 IST — Weekly intel digest.
    Builds digest for all 3 markets, sends to Discord, optionally exports to Obsidian.
    Dedup guard prevents duplicate sends on scheduler restart within the same 23h window."""
    if _digest_already_sent("weekly", cooldown_hours=23):
        logger.info(
            "[Scheduler] Weekly digest dedup: already sent within 23h — skipping"
        )
        return

    logger.info("[Scheduler] Weekly intel digest starting")
    failure_count = 0
    try:
        from utils.weekly_digest import WeeklyIntelDigest
        from utils.discord_notifier import send_weekly_digest
        from utils.obsidian_export import ObsidianExport

        markets = [m.strip() for m in TARGET_MARKETS]
        results = []
        for market in markets:
            try:
                digest = WeeklyIntelDigest()
                result = digest.build(market)
                results.append(result)
            except Exception as exc:
                failure_count += 1
                logger.warning(
                    "[Scheduler] Weekly digest build failed for {}: {}", market, exc
                )
        if results:
            _mark_digest_sent("weekly")
            send_weekly_digest(results)
            successful = len(results) - failure_count
            logger.info(
                "[Scheduler] Weekly intel digest sent for {}/{} markets ({} failures)",
                successful,
                len(results),
                failure_count,
            )
        else:
            logger.warning(
                "[Scheduler] Weekly intel digest: 0 results built — skipping Discord send"
            )
            return
        ObsidianExport.write_weekly(results)
    except Exception as exc:
        logger.warning("[Scheduler] Weekly intel digest failed: {}", exc)


def run_monthly_intel_digest():
    """1st of month 02:00 UTC = 07:30 IST — Monthly intel digest.
    Builds digest for all 3 markets, sends to Discord, optionally exports to Obsidian.
    Dedup guard prevents duplicate sends on scheduler restart within the same 47h window."""
    if _digest_already_sent("monthly", cooldown_hours=47):
        logger.info(
            "[Scheduler] Monthly digest dedup: already sent within 47h — skipping"
        )
        return

    logger.info("[Scheduler] Monthly intel digest starting")
    failure_count = 0
    try:
        from utils.monthly_digest import MonthlyIntelDigest
        from utils.discord_notifier import send_monthly_digest
        from utils.obsidian_export import ObsidianExport

        markets = [m.strip() for m in TARGET_MARKETS]
        results = []
        for market in markets:
            try:
                digest = MonthlyIntelDigest()
                result = digest.build(market)
                results.append(result)
            except Exception as exc:
                failure_count += 1
                logger.warning(
                    "[Scheduler] Monthly digest build failed for {}: {}", market, exc
                )
        if results:
            _mark_digest_sent("monthly")
            send_monthly_digest(results)
            successful = len(results) - failure_count
            logger.info(
                "[Scheduler] Monthly intel digest sent for {}/{} markets ({} failures)",
                successful,
                len(results),
                failure_count,
            )
        else:
            logger.warning(
                "[Scheduler] Monthly intel digest: 0 results built — skipping Discord send"
            )
            return
        ObsidianExport.write_monthly(results)
    except Exception as exc:
        logger.warning("[Scheduler] Monthly intel digest failed: {}", exc)


def monthly_ceo_letter():
    """1st of month 04:00 UTC — Generate monthly CEO letter.

    Gathers PerformanceDigest for the quarter, agent_runs summary, and
    optimizer findings. Writes a lighter CEO letter to outputs/shareholder_letters/.
    Sends 3-line Discord summary to #ops.
    """
    try:
        from utils.performance_digest import PerformanceDigest
        from pathlib import Path
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        quarter_num = (now.month - 1) // 3 + 1
        quarter = f"Q{quarter_num}-{now.year}"

        digest = PerformanceDigest.build(quarter)

        total_agent_runs = 0
        try:
            with get_engine().connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM agent_runs WHERE created_at >= DATE_TRUNC('month', NOW())"
                    )
                ).fetchone()
                total_agent_runs = row[0] if row else 0
        except Exception:
            pass

        optimizer_note = ""
        try:
            from utils.optimizer_report import OptimizerReport

            report = OptimizerReport.from_last_report()
            if report and report.top_recommendation:
                optimizer_note = report.top_recommendation[:200]
        except Exception:
            pass

        deal_count = digest.get("deal_metrics", {}).get("deal_count", 0)
        avg_irr = digest.get("deal_metrics", {}).get("avg_irr_pct", "N/A")
        new_projects_total = sum(
            p.get("project_count", 0) for p in digest.get("new_projects", [])
        )
        over_budget = digest.get("token_efficiency", {}).get("over_budget_count", 0)

        letter = (
            f"# Monthly CEO Letter — {month}\n\n"
            f"**Quarter:** {quarter}\n"
            f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"## Month in Review\n\n"
            f"The system evaluated {deal_count} deal(s) this month "
            f"with an average IRR of {avg_irr}%. "
            f"We tracked {new_projects_total} new project(s) across our markets.\n\n"
            f"## Top Intelligence Moments\n\n"
            f"1. {deal_count} deal(s) processed through the full evaluate pipeline.\n"
            f"2. {new_projects_total} new project(s) detected across target markets.\n"
            f"3. {total_agent_runs} agent run(s) completed this month.\n\n"
            f"## System Health\n\n"
            f"Token budget overruns: {over_budget} agent(s) exceeded budget. "
            f"{optimizer_note if optimizer_note else 'No optimizer recommendations available.'}\n\n"
            f"## Next Month Focus\n\n"
            f"Continue monitoring {quarter} performance targets, "
            f"address token budget optimization recommendations, "
            f"and maintain pipeline throughput.\n\n"
            f"---\n*LLS CEO • Automated monthly brief*"
        )

        output_dir = Path("outputs/shareholder_letters")
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{month}_Monthly_CEO_Letter.md"
        path.write_text(letter, encoding="utf-8")

        summary = (
            f"Monthly CEO letter — {month} | "
            f"{deal_count} deals, {new_projects_total} new projects, "
            f"{over_budget} over-budget agents | "
            f"Letter saved: {path.name}"
        )
        try:
            from utils.discord_notifier import send

            send("system", "Monthly CEO Letter", summary)
        except Exception:
            pass

        logger.info("[Scheduler] Monthly CEO letter saved to {} — {}", path, summary)
    except Exception as exc:
        logger.warning("[Scheduler] Monthly CEO letter failed (non-fatal): {}", exc)


def weekly_pr_brief():
    """Monday ~07:30 IST PR brief digest — Discord to #bd-opportunities.
    Runs at 02:00 UTC (07:30 IST). Gathers brand mentions, competitor launches,
    and generates LinkedIn preview. Never crashes. 23h dedup guard prevents
    re-firing if scheduler restarts mid-day."""
    try:
        from utils.brand_monitor import BrandMentionMonitor, format_pr_brief_digest
        from intelligence.competitive_intel import CompetitiveIntelEngine
        from utils.discord_notifier import send
        from config.scheduler.maintenance_jobs import _ops_already_alerted

        title = "Weekly PR Brief"
        if _ops_already_alerted(title, cooldown_hours=23):
            logger.info(
                "[Scheduler] PR brief dedup: already sent within 23h — skipping"
            )
            return

        monitor = BrandMentionMonitor()
        mentions = monitor.scan_mentions("LLS", 7)

        engine = CompetitiveIntelEngine()
        launches = engine.new_launches(market=None, days=7)

        linkedin_preview = ""
        try:
            from utils.content_pipeline import ContentPipeline

            pipeline = ContentPipeline()
            result = pipeline.run(
                market="Yelahanka", survey_no="system", deal_type="pr"
            )
            linkedin_preview = result.get("linkedin_post", "")
        except Exception as exc:
            logger.debug("[Scheduler] PR brief LinkedIn preview skipped: {}", exc)

        digest = format_pr_brief_digest(mentions, launches, linkedin_preview)
        send("bd_opportunities", title, digest)

        logger.info(
            "[Scheduler] PR brief sent — {} mentions, {} launches, {} chars",
            len(mentions),
            len(launches),
            len(digest),
        )
    except Exception as exc:
        logger.warning("[Scheduler] Weekly PR brief failed (non-fatal): {}", exc)


def weekly_process_audit():
    """Sunday 03:00 UTC — Process automation audit cycle.
    LogAnalyst → EfficiencyOptimizer → RunbookDocumenter → Discord #ops summary."""
    try:
        from agents.log_analyst_agent import LogAnalystAgent
        from agents.efficiency_optimizer_agent import EfficiencyOptimizerAgent
        from agents.runbook_documenter_agent import RunbookDocumenterAgent
        from utils.discord_notifier import send
        from config.scheduler.maintenance_jobs import _ops_already_alerted

        title = "Weekly Process Audit"
        if _ops_already_alerted(title, cooldown_hours=47):
            logger.info(
                "[Scheduler] Process audit dedup: already sent within 47h — skipping"
            )
            return

        log_agent = LogAnalystAgent()
        log_result = log_agent.run()
        report = log_result.get("report", {})

        eff_agent = EfficiencyOptimizerAgent()
        eff_result = eff_agent.run(bottleneck_report=report)
        proposal = eff_result.get("proposal", {})

        doc_agent = RunbookDocumenterAgent()
        doc_result = doc_agent.run(
            bottleneck_report=report, improvement_proposal=proposal
        )

        summary = (
            f"Process Audit complete — Bottleneck: {report.get('bottleneck_stage', 'none')} | "
            f"Finding: {report.get('top_finding', '')[:120]} | "
            f"Proposal: {proposal.get('title', '')[:80]} | "
            f"Runbook: {doc_result.get('path', '')}"
        )
        if proposal.get("priority") == "HIGH":
            send("system", "Weekly Process Audit", summary)
        logger.info("[Scheduler] Process audit complete — {}", summary)
    except Exception as exc:
        logger.warning("[Scheduler] Process audit failed (non-fatal): {}", exc)


def run_compliance_check():
    """Daily LLS Compliance Calendar check — 08:00 IST (T-704).
    check_upcoming_deadlines() handles Discord internally; this wrapper logs outcome."""
    try:
        from utils.lls_compliance_calendar import check_upcoming_deadlines

        alerts = check_upcoming_deadlines()
        logger.info(
            "[ComplianceCalendar] Daily check done — {} deadline(s) within 30 days",
            len(alerts),
        )
    except Exception as exc:
        logger.warning("[Scheduler] Compliance check failed (non-fatal): {}", exc)


def run_ledger_verdict_digest():
    """Monthly prediction ledger verdict digest — 1st of month 08:00 UTC.
    Queries ledger for verdict breakdown, identifies best/worst claims,
    posts summary to #intel-reports. 47h dedup guard matches monthly_intel_digest."""
    try:
        from utils.db import get_engine as _ledger_engine
        from utils.discord_notifier import send as _digest_send
        from datetime import datetime, timezone

        if _digest_already_sent("ledger_verdict", cooldown_hours=47):
            logger.info("[LedgerDigest] Dedup: already sent within 47h — skipping")
            return

        engine = _ledger_engine()
        with engine.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM prediction_ledger")
            ).scalar() or 0
            hit = conn.execute(
                text("SELECT COUNT(*) FROM prediction_ledger WHERE verdict = 'hit'")
            ).scalar() or 0
            miss = conn.execute(
                text("SELECT COUNT(*) FROM prediction_ledger WHERE verdict = 'miss'")
            ).scalar() or 0
            psf_hit = conn.execute(
                text("SELECT COUNT(*) FROM prediction_ledger WHERE source_module = 'psf_forecaster' AND verdict = 'hit'")
            ).scalar() or 0
            psf_total = conn.execute(
                text("SELECT COUNT(*) FROM prediction_ledger WHERE source_module = 'psf_forecaster' AND verdict IS NOT NULL")
            ).scalar() or 0
            opp_hit = conn.execute(
                text("SELECT COUNT(*) FROM prediction_ledger WHERE source_module = 'opportunity_engine' AND verdict = 'hit'")
            ).scalar() or 0
            opp_total = conn.execute(
                text("SELECT COUNT(*) FROM prediction_ledger WHERE source_module = 'opportunity_engine' AND verdict IS NOT NULL")
            ).scalar() or 0
            best_row = conn.execute(
                text("""
                    SELECT claim_text FROM prediction_ledger
                    WHERE verdict = 'hit' ORDER BY confidence DESC NULLS LAST LIMIT 1
                """)
            ).fetchone()
            worst_row = conn.execute(
                text("""
                    SELECT claim_text FROM prediction_ledger
                    WHERE verdict = 'miss' ORDER BY confidence DESC NULLS LAST LIMIT 1
                """)
            ).fetchone()

        month = datetime.now(timezone.utc).strftime("%B %Y")
        hit_rate = hit / max(hit + miss, 1)
        best_text = (best_row[0][:120] + "...") if best_row and len(best_row[0]) > 120 else (best_row[0] if best_row else "N/A")
        worst_text = (worst_row[0][:120] + "...") if worst_row and len(worst_row[0]) > 120 else (worst_row[0] if worst_row else "N/A")

        msg = (
            f"📊 PREDICTION LEDGER — {month}\n"
            f"Total: {total} claims | Hit rate: {hit_rate:.0%}\n"
            f"PSF: {psf_hit}/{psf_total} | Opportunities: {opp_hit}/{opp_total}\n"
            f"Best call: {best_text} ✅\n"
            f"Worst miss: {worst_text} ❌"
        )
        _digest_send("intel_reports", f"📊 Prediction Ledger — {month}", msg)
        _mark_digest_sent("ledger_verdict")
        logger.info("[LedgerDigest] Sent verdict digest: {} claims, {:.0%} hit rate", total, hit_rate)
    except Exception as exc:
        logger.warning("[LedgerDigest] Failed (non-fatal): {}", exc)


def register_jobs(scheduler: BlockingScheduler, safe_job: Callable[..., object]) -> None:
    """Register digest-related scheduler jobs."""
    from apscheduler.triggers.cron import CronTrigger
    from config.settings import SCHEDULER_ENABLE_ORG_SIM

    # Weekly memory digest — Monday 04:00 IST (after conflict detection)
    scheduler.add_job(
        lambda: safe_job(run_weekly_digest, "weekly_digest"),
        CronTrigger(day_of_week="mon", hour=4, minute=0, timezone="Asia/Kolkata"),
        id="weekly_digest",
        name="Weekly Memory Digest (top-5 facts per market)",
        misfire_grace_time=3600,
    )
    # Daily LLS Compliance Calendar check — 08:00 IST (T-704)
    scheduler.add_job(
        lambda: safe_job(run_compliance_check, "compliance_check"),
        CronTrigger(hour=8, minute=0),
        id="compliance_check",
        name="Daily LLS Compliance Calendar Check",
        misfire_grace_time=3600,
    )
    # Weekly PR brief digest — Monday 02:00 UTC (gated)
    if SCHEDULER_ENABLE_ORG_SIM:
        scheduler.add_job(
            lambda: safe_job(weekly_pr_brief, "weekly_pr_brief"),
            CronTrigger(day_of_week="mon", hour=2, minute=0, timezone="UTC"),
            id="weekly_pr_brief",
            name="Monday PR Brief Digest (Brand Mentions + LinkedIn)",
            misfire_grace_time=3600,
        )
    # Weekly process audit — Sunday 03:00 UTC (gated)
    if SCHEDULER_ENABLE_ORG_SIM:
        scheduler.add_job(
            lambda: safe_job(weekly_process_audit, "weekly_process_audit"),
            CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="UTC"),
            id="weekly_process_audit",
            name="Weekly Process Audit (LogAnalyst → Optimizer → Runbook)",
            misfire_grace_time=7200,
        )
    # Weekly intel digest — Monday 01:30 UTC = 07:00 IST (Sprint 76, T-1057)
    scheduler.add_job(
        lambda: safe_job(run_weekly_intel_digest, "weekly_intel_digest"),
        CronTrigger(day_of_week="mon", hour=1, minute=30, timezone="UTC"),
        id="weekly_intel_digest",
        name="Monday Weekly Intel Digest → Discord intel_reports",
        misfire_grace_time=3600,
    )
    # Monthly intel digest — 1st of month 02:00 UTC = 07:30 IST (Sprint 76, T-1057)
    scheduler.add_job(
        lambda: safe_job(run_monthly_intel_digest, "monthly_intel_digest"),
        CronTrigger(day=1, hour=2, minute=0, timezone="UTC"),
        id="monthly_intel_digest",
        name="Monthly Intel Digest → Discord intel_reports",
        misfire_grace_time=7200,
    )
    # Monthly CEO letter — 1st of month at 04:00 UTC (gated)
    if SCHEDULER_ENABLE_ORG_SIM:
        scheduler.add_job(
            lambda: safe_job(monthly_ceo_letter, "monthly_ceo_letter"),
            CronTrigger(day=1, hour=4, minute=0, timezone="UTC"),
            id="monthly_ceo_letter",
            name="Monthly CEO Letter (PerformanceDigest + agent_runs summary)",
            misfire_grace_time=7200,
        )
    # Monthly prediction ledger verdict digest — 1st of month 08:00 UTC (GATE-111, T-1243)
    scheduler.add_job(
        lambda: safe_job(run_ledger_verdict_digest, "ledger_verdict_digest"),
        CronTrigger(day=1, hour=8, minute=0, timezone="UTC"),
        id="ledger_verdict_digest",
        name="Monthly Prediction Ledger Verdict Digest → #intel-reports",
        misfire_grace_time=7200,
    )
