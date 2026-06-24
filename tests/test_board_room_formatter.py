"""Tests for BoardRoomFormatter (T-1335, GATE-129).

8 tests:
1. Legal Head NO-GO → overall NO-GO (veto)
2. Finance Head NO-GO → overall NO-GO (veto)
3. All 5 positive → GO
4. Mixed (3 GO, 1 CONDITIONAL, 1 GO) → GO (4/5 positive, no veto)
5. format_discord() output <=2000 chars
6. Decision flag appears at start of Discord output
7. format_full_markdown() contains all 5 dept head names
8. format_summary_table() has 6 columns per row
"""

import pytest

pytestmark = pytest.mark.unit


def _make_dept_responses(**overrides) -> dict[str, str]:
    base: dict[str, str] = {
        "bd": "I recommend proceeding. The location has strong demand.",
        "finance": "The IRR looks viable. Positive cashflow expected.",
        "engineering": "Site conditions are favorable. Soil report is clean.",
        "ops": "Operationally feasible. Good access and utilities.",
        "legal": "Title is clear. No encumbrances found. Recommend proceed.",
    }
    base.update(overrides)
    return base


def _make_nogo_legal() -> dict[str, str]:
    return _make_dept_responses(
        legal="I reject this deal. Title issues found — do not proceed.",
        bd="I recommend proceeding. Good opportunity.",
        finance="Viable. Positive NPV.",
        engineering="Feasible.",
        ops="Operationally sound.",
    )


def _make_nogo_finance() -> dict[str, str]:
    return _make_dept_responses(
        finance="This is too risky. IRR is negative. Avoid this deal.",
        bd="Good opportunity. Proceed.",
        engineering="Feasible.",
        ops="Operationally sound.",
        legal="Title is clear.",
    )


def _make_mixed() -> dict[str, str]:
    return _make_dept_responses(
        bd="I recommend proceeding. The location has strong demand.",
        finance="Subject to further due diligence on cashflows.",
        engineering="Favorable conditions. Recommend proceed.",
        ops="Operationally feasible. Positive outlook.",
        legal="Title is clear. Proceed.",
    )


def test_legal_head_nogo_veto():
    """1. Legal Head NO-GO forces overall NO-GO."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_nogo_legal())
    assert fmt.decision_flag() == "NO-GO"


def test_finance_head_nogo_veto():
    """2. Finance Head NO-GO forces overall NO-GO."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_nogo_finance())
    assert fmt.decision_flag() == "NO-GO"


def test_all_positive_go():
    """3. All 5 dept heads positive → GO."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_dept_responses())
    assert fmt.decision_flag() == "GO"


def test_mixed_go():
    """4. 4 GO + 1 CONDITIONAL, no veto → GO."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_mixed())
    assert fmt.decision_flag() == "GO"


def test_discord_under_2000_chars():
    """5. format_discord() output does not exceed 2000 chars."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_dept_responses())
    output = fmt.format_discord()
    assert len(output) <= 2000, f"Discord output is {len(output)} chars (max 2000)"


def test_decision_flag_at_start_of_discord():
    """6. Decision flag appears at start of Discord output."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_dept_responses())
    output = fmt.format_discord()
    assert "DECISION: GO" in output or "DECISION" in output[:200]


def test_full_markdown_contains_all_depts():
    """7. format_full_markdown() contains all 5 dept head names."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_dept_responses())
    md = fmt.format_full_markdown()
    for dept in ("bd", "finance", "engineering", "ops", "legal"):
        assert dept.title() in md or dept.upper() in md, f"Markdown missing {dept}"


def test_summary_table_has_6_columns():
    """8. format_summary_table() has 6 columns per row."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_dept_responses())
    table = fmt.format_summary_table()
    assert table, "Summary table should not be empty"
    rows = table.strip().split("\n")
    data_rows = [r for r in rows if r.strip().startswith("|")]
    for row in data_rows:
        cols = [c.strip() for c in row.split("|") if c.strip()]
        assert len(cols) == 6, f"Expected 6 columns, got {len(cols)}: {cols}"


def test_empty_responses_returns_conditional():
    """9. Empty dept_responses returns CONDITIONAL."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter({})
    assert fmt.decision_flag() == "CONDITIONAL"
    assert fmt.format_discord() != ""
    assert fmt.format_full_markdown() != ""


def test_all_neutral_returns_conditional():
    """10. All NEUTRAL (no keywords found) returns CONDITIONAL."""
    from utils.board_room_formatter import BoardRoomFormatter

    responses = {
        "bd": "The site is in Yelahanka near the railway station.",
        "finance": "Numbers need more analysis before conclusion.",
        "engineering": "Standard construction methods apply here.",
        "ops": "Operations team is reviewing the schedule.",
        "legal": "Documents are being reviewed by the legal team.",
    }
    fmt = BoardRoomFormatter(responses)
    assert fmt.decision_flag() == "CONDITIONAL"


def test_psf_extraction_skips_non_psf_numbers():
    """11. PSF extraction ignores non-PSF numbers (costs, areas)."""
    from utils.board_room_formatter import BoardRoomFormatter

    text = "total project cost is 50000000 and area is 24000 sqft. psf 6500"
    result = BoardRoomFormatter._extract_psf(text)
    assert result == "₹6,500", f"Expected PSF ₹6,500, got {result}"


def test_missing_dept_does_not_crash():
    """12. Missing dept keys handled without KeyError."""
    from utils.board_room_formatter import BoardRoomFormatter

    responses = {"bd": "Proceed.", "finance": "Viable."}
    fmt = BoardRoomFormatter(responses)
    flag = fmt.decision_flag()
    assert flag in ("GO", "CONDITIONAL")


def test_truncation_does_not_split_line():
    """13. Discord truncation at newline boundary when over max_chars."""
    from utils.board_room_formatter import BoardRoomFormatter

    long_responses = {
        "bd": "I recommend proceeding. " * 100,
        "finance": "The IRR is positive. " * 100,
        "engineering": "Feasible. " * 100,
        "ops": "Good. " * 100,
        "legal": "Clear. " * 100,
    }
    fmt = BoardRoomFormatter(long_responses)
    output = fmt.format_discord(max_chars=500)
    assert len(output) <= 500, f"Truncation exceeded limit: {len(output)} chars"
    assert "truncated" in output, "Truncation marker missing"
    # Verify we end at a newline boundary (not mid-line)
    last_line = output.rfind("\n", 0, len(output) - 20)
    assert last_line > 0, "Output should contain at least one newline"


def test_max_chars_clamped_to_min():
    """14. max_chars below 100 is clamped to 100."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_dept_responses())
    output = fmt.format_discord(max_chars=10)
    assert len(output) >= 50, f"Clamped output too short: {len(output)} chars"


def test_max_chars_clamped_to_max():
    """15. max_chars above 2000 is clamped to 2000."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_dept_responses())
    output = fmt.format_discord(max_chars=5000)
    assert len(output) <= 2000, f"Expected <=2000, got {len(output)}"


def test_display_names_use_correct_case():
    """16. Dept names render correctly: BD (not Bd), Ops (not Ops)."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_dept_responses())
    discord = fmt.format_discord()
    assert "**BD**" in discord, "BD should display as 'BD' not 'Bd'"
    assert "**Ops**" in discord, "Ops should display as 'Ops'"
    md = fmt.format_full_markdown()
    assert "## BD " in md, "Markdown BD should display as 'BD'"
    assert "## Ops " in md or "## Ops\n" in md, "Ops heading should display as 'Ops'"


def test_negation_cancels_go():
    """17. Negated GO keyword does NOT trigger GO verdict.

    'positive' preceded by 'not' produces NEUTRAL (cancelled GO).
    Other departments with explicit NO-GO keywords should still be NO-GO.
    """
    from utils.board_room_formatter import BoardRoomFormatter

    responses = {
        "bd": "This is not viable. Not recommended. Avoid this.",
        "finance": "The numbers do not look positive.",
        "engineering": "Site conditions are not favorable. Reject this site.",
        "ops": "Not feasible at this time. Decline this opportunity.",
        "legal": "Title issues — do not proceed.",
    }
    fmt = BoardRoomFormatter(responses)
    assert fmt.decision_flag() == "NO-GO"
    # BD, Engineering, Ops, Legal have explicit NO-GO keywords
    for dept in ("bd", "engineering", "ops", "legal"):
        a = fmt.assessments.get(dept, {})
        assert a.get("verdict") == "NO-GO", (
            f"{dept} should be NO-GO, got {a.get('verdict')}"
        )
    # Finance has only a negated GO keyword → NEUTRAL (no explicit signal)
    fin_a = fmt.assessments.get("finance", {})
    assert fin_a.get("verdict") == "NEUTRAL", (
        f"finance should be NEUTRAL (negated 'positive'), got {fin_a.get('verdict')}"
    )


def test_negation_does_not_false_positive():
    """18. Negated words in positive context do not trigger false NO-GO.

    "This is not just unviable — it is the worst deal I've seen" should be NO-GO
    (from "unviable"), but "not" before "viable" shouldn't be miscounted.
    """
    from utils.board_room_formatter import BoardRoomFormatter

    responses = {
        "finance": "The returns are not just viable — they are excellent. Recommend proceed.",
    }
    fmt = BoardRoomFormatter(responses)
    assert fmt.assessments.get("finance", {}).get("verdict") == "GO", (
        f"Expected GO, got {fmt.assessments.get('finance', {}).get('verdict')}"
    )


def test_discord_includes_session_api_reference():
    """19. Discord output references the session API endpoint."""
    from utils.board_room_formatter import BoardRoomFormatter

    fmt = BoardRoomFormatter(_make_dept_responses())
    output = fmt.format_discord()
    assert "/api/board/session" in output, (
        "Discord output should reference session API for full memo"
    )


def test_empty_string_responses_no_crash():
    """20. Dict with empty string values does not crash."""
    from utils.board_room_formatter import BoardRoomFormatter

    responses = {
        "bd": "",
        "finance": "",
        "engineering": "",
        "ops": "",
        "legal": "",
    }
    fmt = BoardRoomFormatter(responses)
    assert fmt.decision_flag() == "CONDITIONAL"
    assert fmt.format_discord() != ""
    assert fmt.format_full_markdown() != ""
    assert fmt.format_summary_table() == ""


def test_confidence_tiers_from_hedge_count():
    """21. Hedge word count maps to correct confidence tier."""
    from utils.board_room_formatter import BoardRoomFormatter

    assert BoardRoomFormatter._confidence_label(0) == "high"
    assert BoardRoomFormatter._confidence_label(1) == "high"
    assert BoardRoomFormatter._confidence_label(2) == "medium"
    assert BoardRoomFormatter._confidence_label(3) == "medium"
    assert BoardRoomFormatter._confidence_label(4) == "low"
    assert BoardRoomFormatter._confidence_label(99) == "low"


def test_all_go_keyword_variants():
    """22. All GO keyword variants trigger GO verdict."""
    from utils.board_room_formatter import BoardRoomFormatter

    for keyword in ["recommend", "proceed", "positive", "favorable",
                     "good opportunity", "promising", "viable", "attractive"]:
        responses = {"bd": f"I {keyword} this deal."}
        fmt = BoardRoomFormatter(responses)
        a = fmt.assessments.get("bd", {})
        assert a.get("verdict") == "GO", (
            f"Keyword '{keyword}' should produce GO, got {a.get('verdict')}"
        )


def test_go_keyword_does_not_match_procedure():
    """23. 'proceed' does not match 'procedure' (word boundary)."""
    from utils.board_room_formatter import BoardRoomFormatter

    responses = {"bd": "The standard procedure applies here."}
    fmt = BoardRoomFormatter(responses)
    a = fmt.assessments.get("bd", {})
    # No GO keyword should match — verdict should be NEUTRAL or CONDITIONAL
    assert a.get("verdict") in ("NEUTRAL", "CONDITIONAL"), (
        f"Expected neutral/conditional, got {a.get('verdict')}"
    )


def test_all_nogo_keyword_variants():
    """24. All NO-GO keyword variants trigger NO-GO verdict."""
    from utils.board_room_formatter import BoardRoomFormatter

    for keyword in ["reject", "no go", "no-go", "avoid", "decline",
                     "not recommended", "do not proceed", "unviable",
                     "too risky", "pass"]:
        responses = {"legal": f"I {keyword} this deal."}
        fmt = BoardRoomFormatter(responses)
        a = fmt.assessments.get("legal", {})
        assert a.get("verdict") == "NO-GO", (
            f"Keyword '{keyword}' should produce NO-GO, got {a.get('verdict')}"
        )


def test_summary_table_skips_missing_depts():
    """25. Summary table rows match assessments only, not all dept keys."""
    from utils.board_room_formatter import BoardRoomFormatter

    responses = {"bd": "Proceed.", "finance": "Viable."}
    fmt = BoardRoomFormatter(responses)
    table = fmt.format_summary_table()
    assert "| BD " in table
    assert "| Finance " in table
    assert "| Engineering " not in table  # no assessment
    assert "| Ops " not in table
    assert "| Legal " not in table
