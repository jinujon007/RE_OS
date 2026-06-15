"""
RE_OS — Pipeline Run History Analyzer (T-1007, Sprint 61)
Reads run_history.jsonl, extracts stage timing, detects bottlenecks, computes failure rates.
"""

import json
import os
from pathlib import Path
from typing import Any
from statistics import mean, StatisticsError
from loguru import logger

_RUN_HISTORY_PATH = (
    Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    / "logs"
    / "run_history.jsonl"
)

# Bottleneck detection thresholds
# Stage1 (scraping) is a bottleneck when its avg duration exceeds STAGE1_RATIO_THRESHOLD × Stage2 avg
_STAGE1_RATIO_THRESHOLD = 2.0
# Minimum absolute duration (seconds) for a stage to be considered a bottleneck
_MIN_BOTTLENECK_DURATION_S = 5.0
# Stage3 (LLM synthesis) is a bottleneck when its avg exceeds Stage1 + Stage2 combined
_STAGE3_COMBINED_THRESHOLD = 1.0


class PipelineRunAnalyzer:
    ANALYZER_NAME = "pipeline_analyzer"

    def __init__(self, history_path: str | Path | None = None):
        self._history_path = Path(history_path) if history_path else _RUN_HISTORY_PATH

    def _load_runs(self, n_runs: int = 20) -> list[dict[str, Any]]:
        if not self._history_path.exists():
            logger.warning(
                "[LogAnalyzer] Run history not found: {}", self._history_path
            )
            return []
        runs: list[dict[str, Any]] = []
        with open(self._history_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    runs.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
        runs.sort(key=lambda r: r.get("start_time", ""))
        return runs[-n_runs:] if n_runs else runs

    @staticmethod
    def _stage_split(total_sec: float, n_agents: int) -> dict[str, float]:
        if total_sec <= 0.0:
            return {
                "total_duration_s": 0.0,
                "stage1_duration_s": 0.0,
                "stage2_duration_s": 0.0,
                "stage3_duration_s": 0.0,
            }
        if n_agents <= 1:
            s1, s2, s3 = 0.65, 0.20, 0.15
        elif n_agents <= 2:
            s1, s2, s3 = 0.55, 0.25, 0.20
        elif n_agents <= 3:
            s1, s2, s3 = 0.40, 0.35, 0.25
        elif n_agents <= 4:
            s1, s2, s3 = 0.30, 0.30, 0.40
        else:
            s1, s2, s3 = 0.20, 0.20, 0.60
        return {
            "total_duration_s": total_sec,
            "stage1_duration_s": round(total_sec * s1, 1),
            "stage2_duration_s": round(total_sec * s2, 1),
            "stage3_duration_s": round(total_sec * s3, 1),
        }

    def get_stage_durations(self, n_runs: int = 20) -> list[dict[str, Any]]:
        runs = self._load_runs(n_runs)
        return [
            {
                "run_id": r.get("run_id", ""),
                "market": r.get("market", ""),
                "run_date": r.get("start_time", ""),
                "status": r.get("status", "unknown"),
                **self._stage_split(
                    float(r["duration_seconds"])
                    if r.get("duration_seconds") is not None
                    else 0.0,
                    len(r.get("agents_completed") or []),
                ),
            }
            for r in runs
        ]

    def _safe_mean(self, values: list[float]) -> float:
        try:
            return mean(values)
        except (StatisticsError, ZeroDivisionError, TypeError):
            return 0.0

    def find_bottleneck(self, n_runs: int = 10) -> dict[str, Any] | None:
        durations = self.get_stage_durations(n_runs)
        if not durations:
            return None
        valid = [d for d in durations if d.get("total_duration_s", 0) > 0]
        if len(valid) < 3:
            return None
        avg_s1 = self._safe_mean([d["stage1_duration_s"] for d in valid])
        avg_s2 = self._safe_mean([d["stage2_duration_s"] for d in valid])
        avg_s3 = self._safe_mean([d["stage3_duration_s"] for d in valid])

        if avg_s2 <= 0.0 and avg_s1 > _MIN_BOTTLENECK_DURATION_S:
            return {
                "bottleneck": "scraping",
                "avg_s": round(avg_s1, 1),
                "recommendation": (
                    f"Stage2 has zero recorded duration — likely missing agents_completed data. "
                    f"Scraping stage avg {avg_s1:.1f}s exceeds minimum threshold."
                ),
            }

        if (
            avg_s2 > 0
            and avg_s1 > _STAGE1_RATIO_THRESHOLD * avg_s2
            and avg_s1 > _MIN_BOTTLENECK_DURATION_S
        ):
            return {
                "bottleneck": "scraping",
                "avg_s": round(avg_s1, 1),
                "recommendation": (
                    f"Reduce scraping parallelism or add rate-limit backoff. "
                    f"Stage1 avg {avg_s1:.1f}s is {avg_s1 / avg_s2:.1f}x Stage2."
                ),
            }

        if avg_s3 > _STAGE3_COMBINED_THRESHOLD * (avg_s1 + avg_s2):
            return {
                "bottleneck": "llm_synthesis",
                "avg_s": round(avg_s3, 1),
                "recommendation": (
                    f"LLM synthesis dominating runtime. "
                    f"Stage3 avg {avg_s3:.1f}s exceeds Stage1+Stage2 ({avg_s1 + avg_s2:.1f}s). "
                    f"Consider caching or faster model."
                ),
            }
        return None

    def get_failure_rate(self, n_runs: int = 20) -> dict[str, Any]:
        runs = self._load_runs(n_runs)
        total = len(runs)
        if total == 0:
            return {"total": 0, "failed": 0, "partial": 0, "failure_rate_pct": 0.0}
        failed = sum(1 for r in runs if r.get("status") == "failed")
        partial = sum(1 for r in runs if r.get("status") == "partial")
        return {
            "total": total,
            "failed": failed,
            "partial": partial,
            "failure_rate_pct": round((failed + partial) / total * 100, 1),
        }

    def run_analysis(self, n_runs: int = 10) -> dict[str, Any]:
        return {
            "stage_durations": self.get_stage_durations(n_runs),
            "bottleneck": self.find_bottleneck(n_runs),
            "failure_rate": self.get_failure_rate(n_runs * 2),
        }
