"""
RE_OS — Board Room Formatter (T-1332, GATE-129)

Parses dept head outputs, computes GO/CONDITIONAL/NO-GO decision flag,
and formats structured Discord message and full markdown deal memo.

Architecture:
  - Keyword-matching via word-boundary regex (\\b anchors)
  - Negation-aware context detection: "not recommended" cancels GO signal
  - Legal/Finance veto power: either dept NO-GO forces overall NO-GO
  - Hedge-word counting drives confidence tiers (high/medium/low)
  - All formatting methods are idempotent and safe for partial data
"""

from __future__ import annotations

import re
import time
from typing import Any

__all__: list[str] = [
    "BoardRoomFormatter",
]

# ── Constants ──────────────────────────────────────────────────────────────────

_DISCORD_MAX_CHARS: int = 2000
_DISCORD_MIN_CHARS: int = 100
_TRUNC_SAFETY_MARGIN: int = 80
_PSF_RANGE_CAP: int = 2  # max PSF values in range display

_DEPT_DISPLAY_NAMES: dict[str, str] = {
    "bd": "BD",
    "finance": "Finance",
    "engineering": "Engineering",
    "ops": "Ops",
    "legal": "Legal",
}
_DEPT_ORDER = ("bd", "finance", "engineering", "ops", "legal")

_NEGATION_PREFIX_RE = re.compile(
    r"\b(?:not|no|never|neither|nor|without|unlikely|hardly|rarely)\s+",
    re.I,
)


def _word_set(words: frozenset[str]) -> frozenset[str]:
    """Wrap each word in ``\\b`` anchors for word-boundary matching.

    Prevents substring false positives (e.g. "proceed" matching "procedure")
    while still matching inside compound text ("do not proceed is final").
    """
    return frozenset(r"\b" + w + r"\b" for w in words)


_NOGO_PATTERNS: frozenset[str] = _word_set(frozenset({
    "reject", "no go", "no-go", "avoid", "decline", "not recommended",
    "do not proceed", "unviable", "too risky", "pass",
}))
_CONDITIONAL_PATTERNS: frozenset[str] = _word_set(frozenset({
    "subject to", "pending", "conditional", "provided that",
    "depending on", "further review", "contingent",
}))
_GO_PATTERNS: frozenset[str] = _word_set(frozenset({
    "recommend", "proceed", "positive", "favorable",
    "good opportunity", "promising", "viable", "attractive",
}))
_HEDGE_PATTERNS: frozenset[str] = _word_set(frozenset({
    "maybe", "perhaps", "possibly", "might", "could", "seems",
    "appears", "suggest", "consider", "potentially",
}))

_PSF_RE = re.compile(r"""
    (?:               # prefix variants
        psf[\s:]|
        per\s+sq\.?\s*ft|
        rs\.?\s*|
        inr\s*|
        \u20B9
    )
    \s*
    (\d[\d,]*(?:\.\d+)?)   # number with commas / decimals
""", re.I | re.VERBOSE)

_VERDICT_ICONS: dict[str, str] = {
    "GO": "🟢", "CONDITIONAL": "🟡", "NO-GO": "🔴", "NEUTRAL": "⚪",
}
_DECISION_ICONS: dict[str, str] = {
    "GO": "✅", "CONDITIONAL": "⚠️", "NO-GO": "❌",
}
_CONFIDENCE_THRESHOLDS: list[tuple[int, str]] = [
    (1, "high"),
    (3, "medium"),
]


# ── Pattern helpers ────────────────────────────────────────────────────────────


def _has_any(text: str, patterns: frozenset[str]) -> bool:
    """Return True if any regex pattern matches *text*."""
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False


def _count_matches(text: str, patterns: frozenset[str]) -> int:
    """Count how many patterns match *text*."""
    return sum(1 for pat in patterns if re.search(pat, text))


def _is_negated(text: str, match_end: int, max_lookbehind: int = 25) -> bool:
    """Check if a match position is preceded by a negation within lookbehind window.

    Scans the substring preceding *match_end* for negation tokens. A keyword
    like "viable" preceded by "not" (within *max_lookbehind* chars) is treated
    as negation-cancelled rather than a true signal.
    """
    start = max(0, match_end - max_lookbehind)
    prefix = text[start:match_end]
    return bool(_NEGATION_PREFIX_RE.search(prefix))


# ── Metrics helpers (optional — gracefully no-ops if Prometheus not loaded) ────


def _observe_format_duration(elapsed_s: float, format_type: str) -> None:
    """Record formatting duration via Prometheus histogram if available."""
    try:
        from config.metrics import format_duration_seconds
        format_duration_seconds.labels(format_type=format_type).observe(elapsed_s)
    except Exception:
        pass


def _inc_decision_flag_total(flag: str) -> None:
    """Increment decision-flag counter if Prometheus is loaded."""
    try:
        from config.metrics import board_decision_flag_total
        board_decision_flag_total.labels(flag=flag).inc()
    except Exception:
        pass


# ── Core class ─────────────────────────────────────────────────────────────────


class BoardRoomFormatter:
    """Parse dept head assessments → decision flag → structured formats.

    Usage:
        fmt = BoardRoomFormatter(dept_responses_dict)
        flag = fmt.decision_flag()            # "GO" | "CONDITIONAL" | "NO-GO"
        discord_msg = fmt.format_discord()     # <=2000 chars
        markdown    = fmt.format_full_markdown()
        table       = fmt.format_summary_table()
    """

    def __init__(self, dept_responses: dict[str, str]) -> None:
        self._dept_responses: dict[str, str] = dept_responses
        self._assessments: dict[str, dict[str, Any]] = {}
        self._parsed: bool = False
        self._cached_flag: str | None = None

    @property
    def dept_responses(self) -> dict[str, str]:
        return self._dept_responses

    @property
    def assessments(self) -> dict[str, dict[str, Any]]:
        self._ensure_parsed()
        return self._assessments

    # ── Internal parsing ──────────────────────────────────────────────────

    def _ensure_parsed(self) -> None:
        if not self._parsed:
            self._assessments = self._parse_assessments()
            self._parsed = True

    def _parse_assessments(self) -> dict[str, dict[str, Any]]:
        """Extract verdicts per dept head with negation-aware keyword matching.

        Verdict resolution order per department:
        1. NO-GO keywords found and NOT negated → NO-GO
        2. GO keywords found and NOT negated, no CONDITIONAL → GO
        3. CONDITIONAL keywords found → CONDITIONAL
        4. GO keywords found (even if negated) → GO (fallback, negated GO ignored)
        5. Neither → NEUTRAL

        Confidence tiers based on hedge-word count:
        - 0-1 hedges → high
        - 2-3 hedges → medium
        - 4+ hedges → low
        """
        result: dict[str, dict[str, Any]] = {}
        for dept, text in self._dept_responses.items():
            if not text:
                continue
            lower = text.lower()

            # GO / NO-GO detection with negation awareness
            has_nogo = _has_any(lower, _NOGO_PATTERNS)
            has_go = _has_any(lower, _GO_PATTERNS)
            has_cond = _has_any(lower, _CONDITIONAL_PATTERNS)
            hedge_count = _count_matches(lower, _HEDGE_PATTERNS)

            # Negation check on GO keywords: if every GO match is negated,
            # downgrade it (default to CONDITIONAL if no other signal).
            go_negated = self._any_go_match_negated(lower)

            if has_nogo:
                verdict = "NO-GO"
            elif has_go and not go_negated and not has_cond:
                verdict = "GO"
            elif has_cond:
                verdict = "CONDITIONAL"
            else:
                verdict = "NEUTRAL"

            result[dept] = {
                "verdict": verdict,
                "hedge_count": hedge_count,
                "confidence": self._confidence_label(hedge_count),
            }
        return result

    @staticmethod
    def _confidence_label(hedge_count: int) -> str:
        """Map hedge count to a confidence tier label."""
        for threshold, label in _CONFIDENCE_THRESHOLDS:
            if hedge_count <= threshold:
                return label
        return "low"

    def _any_go_match_negated(self, lower_text: str) -> bool:
        """Return True if *every* matching GO keyword is negated.

        Scans the GO keyword's match position and checks whether a negation
        token appears within the preceding N characters.
        """
        negated_count = 0
        total_matches = 0
        for pat in _GO_PATTERNS:
            for m in re.finditer(pat, lower_text):
                total_matches += 1
                if _is_negated(lower_text, m.end()):
                    negated_count += 1
        if total_matches == 0:
            return False
        return negated_count == total_matches

    # ── Decision flag ─────────────────────────────────────────────────────

    def _compute_decision_flag(self) -> str:
        """Compute overall decision flag.

        Rules (ordered — first match wins):
        1. Legal or Finance NO-GO → overall NO-GO (veto power)
        2. All responding departments GO → GO
        3. Majority GO (>50% of responding depts) and no veto → GO
        4. Everything else → CONDITIONAL
        """
        self._ensure_parsed()
        verdicts = {d: a["verdict"] for d, a in self.assessments.items()}

        if verdicts.get("legal") == "NO-GO" or verdicts.get("finance") == "NO-GO":
            return "NO-GO"

        total = len(verdicts)
        if total == 0:
            return "CONDITIONAL"

        go_count = sum(1 for v in verdicts.values() if v == "GO")
        if go_count == total:
            return "GO"
        if go_count > total / 2:
            return "GO"
        return "CONDITIONAL"

    def decision_flag(self) -> str:
        """Public accessor — lazy-computes and caches the decision flag."""
        if self._cached_flag is None:
            self._cached_flag = self._compute_decision_flag()
            _inc_decision_flag_total(self._cached_flag)
        return self._cached_flag

    # ── Discord output ────────────────────────────────────────────────────

    def format_discord(self, max_chars: int = _DISCORD_MAX_CHARS) -> str:
        """Format decision summary for Discord. <=2000 chars, truncated cleanly.

        Structure:
          {icon} DECISION: {flag}
          Department Verdicts:
          {dept} → {verdict} (confidence: {tier})
          ...
          Summary table (if assessments exist)
          Full memo available via API
        """
        t0 = time.perf_counter()
        max_chars = max(_DISCORD_MIN_CHARS, min(max_chars, _DISCORD_MAX_CHARS))
        self._ensure_parsed()
        flag = self.decision_flag()
        flag_icon = _DECISION_ICONS.get(flag, "❓")

        lines: list[str] = [
            f"**{flag_icon} DECISION: {flag}**",
            "",
            "**Department Verdicts:**",
        ]
        for dept in _DEPT_ORDER:
            assessment = self.assessments.get(dept)
            if not assessment:
                continue
            v_icon = _VERDICT_ICONS.get(assessment["verdict"], "⚪")
            display = _DEPT_DISPLAY_NAMES.get(dept, dept.title())
            lines.append(
                f"{v_icon} **{display}**: {assessment['verdict']} "
                f"(confidence: {assessment['confidence']})"
            )

        lines.append("")
        table = self.format_summary_table()
        if table:
            lines.append(table)

        lines.append("")
        lines.append(
            "_Full markdown memo: "
            "`GET /api/board/session/{session_id}`_"
        )

        output = "\n".join(lines)
        if len(output) > max_chars:
            output = self._truncate(output, max_chars)

        _observe_format_duration(time.perf_counter() - t0, "discord")
        return output

    # ── Markdown deal memo ─────────────────────────────────────────────────

    def format_full_markdown(self) -> str:
        """Full structured deal memo with per-dept sections.

        Returns markdown with:
        - H1 heading + decision flag
        - One H2 section per department with raw assessment text
        - Verdict + confidence annotation below each section
        """
        t0 = time.perf_counter()
        self._ensure_parsed()
        flag = self.decision_flag()
        parts: list[str] = [
            "# RE_OS Board Room Deal Memo\n",
            f"**Overall Decision: {flag}**\n",
            "---\n",
        ]
        for dept in _DEPT_ORDER:
            text = self.dept_responses.get(dept, "")
            if not text:
                continue
            display = _DEPT_DISPLAY_NAMES.get(dept, dept.title())
            parts.append(f"## {display} Head Assessment\n")
            parts.append(text.strip())
            parts.append("")
            assessment = self.assessments.get(dept)
            if assessment:
                parts.append(
                    f"*Verdict: {assessment['verdict']} — "
                    f"Confidence: {assessment['confidence']}*"
                )
                parts.append("")
        parts.append("---\n")
        parts.append(
            "*Generated by RE_OS Board Room. "
            "Decision flags are advisory — final judgment requires human review.*"
        )
        _observe_format_duration(time.perf_counter() - t0, "markdown")
        return "\n".join(parts)

    # ── Summary table ──────────────────────────────────────────────────────

    def format_summary_table(self) -> str:
        """6-column markdown summary table: Dept | Verdict | Key Risk | Key Opportunity | PSF Range | Confidence.

        Columns:
        - Key Risk: text snippet near a NO-GO keyword match
        - Key Opportunity: text snippet near a GO keyword match
        - PSF Range: PSF values anchored to price-per-square-foot prefixes
        """
        self._ensure_parsed()
        if not self.assessments:
            return ""
        header = "| Dept | Verdict | Key Risk | Key Opportunity | PSF Range | Confidence |"
        sep = "|------|---------|----------|-----------------|-----------|------------|"
        rows = []
        for dept, a in self.assessments.items():
            text = self.dept_responses.get(dept) or ""
            text_lower = text.lower()
            risk = self._extract_snippet(text_lower, _NOGO_PATTERNS)
            opp = self._extract_snippet(text_lower, _GO_PATTERNS)
            psf = self._extract_psf(text_lower)
            display = _DEPT_DISPLAY_NAMES.get(dept, dept.title())
            rows.append(
                f"| {display} | {a['verdict']} | {risk} | {opp} | {psf} | {a['confidence']} |"
            )
        return "\n".join([header, sep] + rows)

    # ── Output helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        """Truncate *text* at a newline boundary near *max_chars*.

        Falls back to char-level truncation if no suitable newline is found
        within the forward window. Never splits a line in the middle.
        """
        if len(text) <= max_chars:
            return text
        cutoff = text.rfind("\n", 0, max_chars)
        if cutoff < max_chars // 2:
            cutoff = max_chars - _TRUNC_SAFETY_MARGIN
            while cutoff > 0 and not text[cutoff:].startswith("\n"):
                cutoff -= 1
            if cutoff <= 0:
                cutoff = max_chars - _TRUNC_SAFETY_MARGIN
        return text[:cutoff].rstrip() + "\n… *truncated*"

    @staticmethod
    def _extract_snippet(text: str, patterns: frozenset[str], max_len: int = 40) -> str:
        """Extract a short snippet containing any keyword pattern match.

        Returns the first match's surrounding context (up to *max_len* chars),
        or an em-dash placeholder when no pattern matches.
        """
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                start = max(0, m.start() - 10)
                end = min(len(text), m.end() + 20)
                snippet = text[start:end].strip()
                if len(snippet) > max_len:
                    snippet = snippet[:max_len].rstrip() + "…"
                return snippet
        return "—"

    @staticmethod
    def _extract_psf(text: str) -> str:
        """Extract up to *N* PSF values anchored to price-per-square-foot keywords.

        Matches patterns like "psf 6500", "₹7,200", "per sq ft 8500".
        Returns a formatted range or single value, or an em-dash if none found.
        """
        matches = _PSF_RE.findall(text)
        if matches:
            values = []
            for m in matches[: _PSF_RANGE_CAP]:
                try:
                    values.append(int(m.replace(",", "")))
                except ValueError:
                    continue
            if len(values) == 2:
                return f"₹{values[0]:,} – ₹{values[1]:,}"
            if len(values) == 1:
                return f"₹{values[0]:,}"
        return "—"
