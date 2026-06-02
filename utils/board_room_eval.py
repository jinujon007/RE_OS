"""
RE_OS — Board Room Response Evaluator (Sprint 35)
Cross-encoder coherence scoring for department head responses.
Flags off-topic responses before they reach the database.
"""

from loguru import logger


class BoardRoomEvaluator:
    def __init__(self, device: str = "cuda"):
        self._encoder = None
        self._device = device if device else "cuda"

    def _get_encoder(self):
        if self._encoder is None:
            try:
                from sentence_transformers import CrossEncoder
                self._encoder = CrossEncoder(
                    "cross-encoder/stsb-distilroberta-base",
                    device=self._device,
                )
            except Exception:
                try:
                    from sentence_transformers import CrossEncoder
                    self._encoder = CrossEncoder(
                        "cross-encoder/stsb-distilroberta-base",
                        device="cpu",
                    )
                    logger.debug("[BoardRoomEval] CUDA unavailable — using CPU fallback")
                except Exception as exc:
                    logger.debug(f"[BoardRoomEval] CrossEncoder load failed: {exc}")
                    return None
        return self._encoder

    def score_coherence(self, question: str, response: str) -> float:
        encoder = self._get_encoder()
        if encoder is None:
            return 1.0

        try:
            pair = (str(question)[:512], str(response)[:512])
            score = encoder.predict([pair])[0]
            return float(score)
        except Exception as exc:
            logger.debug(f"[BoardRoomEval] score_coherence failed: {exc}")
            return 1.0

    def flag_low_coherence(self, questions: dict, responses: dict, threshold: float = 0.35) -> list[str]:
        flagged = []
        if not questions or not responses:
            return flagged
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in questions.items()):
            logger.debug("[BoardRoomEval] questions dict values must be strings")
            return flagged
        for dept_key, question in questions.items():
            response = responses.get(dept_key, "")
            if not response or not isinstance(response, str):
                continue
            score = self.score_coherence(question, response)
            if score < threshold:
                logger.debug(f"[BoardRoomEval] {dept_key} coherence={score:.3f} below threshold={threshold}")
                flagged.append(dept_key)
        return flagged


if __name__ == "__main__":
    brm = BoardRoomEvaluator()
    score = brm.score_coherence("What is the expected IRR for this project?", "The IRR is 18% based on current projections")
    print(f"Coherence score: {score:.4f}")
    flagged = brm.flag_low_coherence(
        {"finance": "What is the IRR?", "legal": "Any RERA issues?"},
        {"finance": "The IRR is 18%", "legal": "The sky is blue and birds are flying"},
        threshold=0.35
    )
    print(f"Flagged depts: {flagged}")