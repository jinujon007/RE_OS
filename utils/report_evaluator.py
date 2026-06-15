"""
RE_OS — Report Evaluator (Sprint 33 — BERTScore Evaluation)
Evaluates intel report quality by computing BERTScore F1 against a reference corpus.
For each candidate, takes the MAX F1 across all references (best-match scoring).
Appends results to outputs/eval_scores.jsonl for weekly trend tracking.
First-ever run downloads roberta-base (~500MB) — requires network.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from loguru import logger

__all__ = ["ReportEvaluator"]


class ReportEvaluator:
    """Evaluate latest intel reports against a reference corpus using BERTScore.

    Multi-reference scoring: for each candidate, computes BERTScore against
    every reference and uses the MAX F1 (best-match). Averages across candidates.

    Reference corpus: manually selected best reports in outputs/references/.
    Downloads roberta-base on first call (~500MB, cached after).
    Fails gracefully if evaluate library or model unavailable.
    """

    def load_references(
        self, ref_dir: str = "outputs/references"
    ) -> tuple[list[str], int]:
        """Load reference texts from ref_dir.

        Returns (texts, failed_count). Returns empty list if dir missing.
        Corrupt files are skipped with a warning.
        """
        ref_path = Path(ref_dir)
        if not ref_path.exists():
            logger.debug(f"[ReportEvaluator] Reference dir not found: {ref_dir}")
            return [], 0
        texts = []
        failed = 0
        for f in sorted(ref_path.glob("*.txt")):
            try:
                texts.append(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception as exc:
                logger.warning(f"[ReportEvaluator] Failed to read {f.name}: {exc}")
                failed += 1
        logger.debug(
            f"[ReportEvaluator] Loaded {len(texts)} reference(s), {failed} failed from {ref_dir}"
        )
        return texts, failed

    def evaluate_latest(
        self,
        outputs_dir: str = "outputs",
        ref_dir: str = "outputs/references",
        scores_path: str = "outputs/eval_scores.jsonl",
    ) -> dict:
        """Compute BERTScore F1 for the latest intel reports vs reference corpus.

        Steps:
          1. Load reference texts from ref_dir.
          2. Find the last 10 intel_report_*.txt files in outputs/.
          3. Load each candidate text (skip if < 100 chars).
          4. For each candidate, compute BERTScore F1 against every reference.
             Take the MAX F1 per candidate (best-match scoring).
          5. Average the max-F1 scores across all candidates.
          6. Append result to eval_scores.jsonl.
          7. Compute delta vs the previous entry (if any).

        Returns dict with keys: score, delta, alert, timestamp, candidates,
        references, ref_failed, status. Returns status="skipped" when no
        candidates exist. Returns status="failed" when compute errors.
        """
        refs, ref_failed = self.load_references(ref_dir)
        if not refs:
            logger.warning("[ReportEvaluator] No references — skipping evaluation")
            return {
                "score": None,
                "delta": None,
                "alert": False,
                "status": "skipped",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "candidates": 0,
                "references": 0,
                "ref_failed": ref_failed,
            }

        output_path = Path(outputs_dir)
        if not output_path.exists():
            logger.debug(f"[ReportEvaluator] Outputs dir not found: {outputs_dir}")
            return {
                "score": None,
                "delta": None,
                "alert": False,
                "status": "skipped",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "candidates": 0,
                "references": len(refs),
                "ref_failed": ref_failed,
            }

        candidates = sorted(output_path.rglob("intel_report_*.txt"))
        candidates = candidates[-10:]
        cand_texts = []
        skipped_files = 0
        for c in candidates:
            try:
                text = c.read_text(encoding="utf-8", errors="ignore")
                if len(text.strip()) >= 100:
                    cand_texts.append(text)
                else:
                    skipped_files += 1
            except Exception:
                skipped_files += 1
                continue

        if not cand_texts:
            logger.info("[ReportEvaluator] No candidate intel reports found")
            return {
                "score": None,
                "delta": None,
                "alert": False,
                "status": "skipped",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "candidates": 0,
                "references": len(refs),
                "ref_failed": ref_failed,
            }

        avg_f1 = self._compute_bertscore(cand_texts, refs)
        if avg_f1 is None:
            logger.warning(
                "[ReportEvaluator] BERTScore computation failed — no score written"
            )
            return {
                "score": None,
                "delta": None,
                "alert": False,
                "status": "failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "candidates": len(cand_texts),
                "references": len(refs),
                "ref_failed": ref_failed,
            }

        timestamp = datetime.now(timezone.utc).isoformat()
        previous_score = self._load_previous_score(scores_path)
        delta = round(avg_f1 - previous_score, 4) if previous_score is not None else 0.0
        alert = delta < -0.05

        entry = {
            "timestamp": timestamp,
            "score": avg_f1,
            "model": "roberta-base",
            "delta": delta,
        }
        self._append_score(scores_path, entry)

        logger.info(
            f"[ReportEvaluator] BERTScore F1={avg_f1:.4f} delta={delta:+.4f} "
            f"{'⚠ ALERT' if alert else 'OK'} "
            f"({len(cand_texts)} candidates, {len(refs)} refs)"
        )
        return {
            "score": avg_f1,
            "delta": delta,
            "alert": alert,
            "status": "ok",
            "timestamp": timestamp,
            "candidates": len(cand_texts),
            "references": len(refs),
            "ref_failed": ref_failed,
            "candidates_skipped": skipped_files,
        }

    def _compute_bertscore(
        self, cand_texts: list[str], refs: list[str]
    ) -> float | None:
        """Compute BERTScore F1 for candidates against all references.

        Filters out empty texts first (would produce NaN).
        For each candidate, takes the maximum F1 across all references
        (best-match scoring). Returns average across candidates, or None on failure.
        Uses 120s timeout for model load (first run may download roberta-base).
        Thread pool with max_workers=1 exists solely for the timeout feature,
        not for parallelism — BERTScore runs sequentially inside the single thread.
        """
        cand_texts = [c for c in cand_texts if c.strip()]
        refs = [r for r in refs if r.strip()]
        if not cand_texts or not refs:
            return None
        try:
            import concurrent.futures
            import evaluate

            def _load_and_score():
                bertscore = evaluate.load(
                    "bertscore", lang="en", model_type="roberta-base"
                )
                max_f1s = []
                for cand in cand_texts:
                    cand_max = 0.0
                    for ref in refs:
                        result = bertscore.compute(
                            predictions=[cand],
                            references=[ref],
                            lang="en",
                            model_type="roberta-base",
                        )
                        f1 = result.get("f1", [0.0])[0]
                        cand_max = max(cand_max, f1)
                    max_f1s.append(cand_max)
                return round(sum(max_f1s) / max(len(max_f1s), 1), 4)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_load_and_score)
                return future.result(timeout=120)
        except concurrent.futures.TimeoutError:
            logger.warning("[ReportEvaluator] BERTScore model load timed out (>120s)")
        except Exception as exc:
            logger.warning(f"[ReportEvaluator] BERTScore compute failed: {exc}")
        return None

    @staticmethod
    def _load_previous_score(scores_path: str) -> float | None:
        """Load the most recent score from eval_scores.jsonl."""
        path = Path(scores_path)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            if lines:
                entry = json.loads(lines[-1])
                score = entry.get("score")
                return float(score) if score is not None else None
        except Exception:
            pass
        return None

    @staticmethod
    def _append_score(scores_path: str, entry: dict):
        """Append one JSON entry to eval_scores.jsonl."""
        path = Path(scores_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    try:
        evaluator = ReportEvaluator()
        result = evaluator.evaluate_latest()
        print(f"Status: {result.get('status', '?')}")
        score = result.get("score")
        print(f"Score: {score:.4f}" if score is not None else "Score: None")
        delta = result.get("delta")
        print(f"Delta: {delta:+.4f}" if delta is not None else "Delta: None")
        print(f"Alert: {result.get('alert', False)}")
        print(f"Candidates: {result.get('candidates', 0)}")
        print(f"References: {result.get('references', 0)}")
        print(f"Ref failures: {result.get('ref_failed', 0)}")
    except ImportError as exc:
        print(f"[ReportEvaluator] Missing dependency: {exc}")
        print("Run: pip install evaluate datasets")
    except Exception as exc:
        print(f"[ReportEvaluator] Error: {exc}")
