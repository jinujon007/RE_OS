"""
RE_OS — Analyst Brief Quality Evaluator
─────────────────────────────────────────
Measures the quality of analyst market briefs over time using ROUGE.
No torch, no GPU, no HuggingFace models — pure Python via rouge-score.

Why ROUGE for market briefs?
  ROUGE-L measures longest common subsequence — good for detecting whether
  a brief covers the same key facts (project names, PSF figures, developer names)
  as a reference brief. We use yesterday's brief as a pseudo-reference.

Scores are stored in agent_runs table for dashboard trending.

Usage:
  from utils.evaluator import BriefEvaluator
  ev = BriefEvaluator()
  score = ev.score(candidate_brief, reference_brief)
  ev.log_score(market, run_id, score)
"""

import json
import os
from datetime import datetime
from pathlib import Path

from loguru import logger

try:
    from rouge_score import rouge_scorer

    _ROUGE_AVAILABLE = True
except ImportError:
    _ROUGE_AVAILABLE = False
    logger.warning("[Evaluator] rouge-score not installed — quality scoring disabled")


class BriefEvaluator:
    """ROUGE-based quality evaluator for analyst market briefs."""

    def __init__(self, output_dir: str = "/app/outputs/eval"):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        if _ROUGE_AVAILABLE:
            self._scorer = rouge_scorer.RougeScorer(
                ["rouge1", "rouge2", "rougeL"], use_stemmer=False
            )

    def score(self, candidate: str, reference: str) -> dict:
        """
        Score a candidate brief against a reference brief.
        Returns dict with rouge1/rouge2/rougeL F1 scores, or zeros if unavailable.
        """
        if not _ROUGE_AVAILABLE:
            return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0, "available": False}
        if not candidate or not reference:
            return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0, "available": True}

        try:
            scores = self._scorer.score(reference, candidate)
            return {
                "rouge1": round(scores["rouge1"].fmeasure, 4),
                "rouge2": round(scores["rouge2"].fmeasure, 4),
                "rougeL": round(scores["rougeL"].fmeasure, 4),
                "available": True,
            }
        except Exception as exc:
            logger.warning(f"[Evaluator] ROUGE scoring failed: {exc}")
            return {"rouge1": 0.0, "rouge2": 0.0, "rougeL": 0.0, "available": False}

    def score_against_previous(self, market: str, current_brief: str) -> dict | None:
        """
        Score current brief against the previous brief for the same market.
        Looks for the most recent .json eval file for this market.
        Returns None if no previous brief exists yet.
        """
        prev_files = sorted(
            self._output_dir.glob(f"eval_{market.lower()}*.json"), reverse=True
        )
        if not prev_files:
            return None

        try:
            prev_data = json.loads(prev_files[0].read_text())
            prev_brief = prev_data.get("brief", "")
            if not prev_brief:
                return None
            return self.score(current_brief, prev_brief)
        except Exception as exc:
            logger.warning(f"[Evaluator] Could not load previous brief: {exc}")
            return None

    def save_brief(
        self, market: str, run_id: str, brief: str, scores: dict | None = None
    ) -> Path:
        """
        Persist a brief and its scores for future comparison.
        Returns path to saved file.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        filename = self._output_dir / f"eval_{market.lower()}_{ts}.json"
        data = {
            "market": market,
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "brief": brief,
            "scores": scores or {},
        }
        filename.write_text(json.dumps(data, indent=2))
        return filename

    def weekly_report(self) -> dict:
        """
        Aggregate last 7 days of eval files into a quality trend report.
        Returns dict with per-market trend data.
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=7)
        markets: dict[str, list] = {}

        for f in self._output_dir.glob("eval_*.json"):
            try:
                data = json.loads(f.read_text())
                ts = datetime.fromisoformat(data.get("timestamp", ""))
                if ts < cutoff:
                    continue
                market = data.get("market", "unknown")
                scores = data.get("scores", {})
                if scores.get("available") and scores.get("rougeL", 0) > 0:
                    markets.setdefault(market, []).append(scores["rougeL"])
            except Exception:
                continue

        report = {}
        for market, score_list in markets.items():
            report[market] = {
                "count": len(score_list),
                "avg_rougeL": round(sum(score_list) / len(score_list), 4),
                "min_rougeL": round(min(score_list), 4),
                "max_rougeL": round(max(score_list), 4),
                "trend": "improving"
                if len(score_list) > 1 and score_list[-1] > score_list[0]
                else "stable",
            }
        return report


def score_and_save(
    market: str,
    run_id: str,
    brief: str,
    output_dir: str = "/app/outputs/eval",
) -> dict:
    """
    Convenience function: score brief against previous, save, return scores.
    Called at end of each intel pipeline run.
    """
    ev = BriefEvaluator(output_dir=output_dir)
    scores = ev.score_against_previous(market, brief)
    ev.save_brief(market, run_id, brief, scores)

    if scores:
        logger.info(
            f"[Evaluator] {market} brief quality — "
            f"ROUGE-L={scores.get('rougeL', 0):.3f} "
            f"ROUGE-1={scores.get('rouge1', 0):.3f}"
        )
    else:
        logger.info(f"[Evaluator] {market} first brief saved — no prior reference")

    return scores or {}


if __name__ == "__main__":
    ev = BriefEvaluator(output_dir="outputs/eval")
    report = ev.weekly_report()
    if report:
        print("Weekly quality report:")
        for market, stats in report.items():
            print(
                f"  {market}: avg ROUGE-L={stats['avg_rougeL']:.3f} "
                f"over {stats['count']} briefs ({stats['trend']})"
            )
    else:
        print("No eval data yet. Run the pipeline to generate briefs.")
