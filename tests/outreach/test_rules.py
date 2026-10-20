# ruff: noqa: RUF001  -- Chinese greetings carry full-width punctuation by design.
from jobagent.outreach.rules import first_greeting_problems

GOOD = (
    "您好，我现任 AI 产品负责人，主导初创公司多款 Agent 产品从 0 到 1 开发，"
    "产品入选《2026 某某案例集》优秀案例。方便聊聊吗？"
)


def test_a_compliant_greeting_has_no_problems() -> None:
    assert first_greeting_problems(GOOD) == []


def test_length_counts_non_whitespace_characters() -> None:
    assert "too_long" in first_greeting_problems("您" * 121)
    assert "too_long" not in first_greeting_problems("您 " * 120)


def test_numbers_are_refused_outside_the_two_exceptions() -> None:
    assert "contains_number" in first_greeting_problems("专家修订率从七成降到 26%。方便聊聊吗？")
    assert "contains_number" in first_greeting_problems("做过 5 年投研。方便聊聊吗？")
    assert "contains_number" in first_greeting_problems("覆盖１０００名创业者。")
    assert "contains_number" not in first_greeting_problems(GOOD)


def test_internal_terms_and_cliches_are_refused() -> None:
    assert "banned_phrase:修订率" in first_greeting_problems("专家修订率明显下降。")
    assert "banned_phrase:很感兴趣" in first_greeting_problems("我对贵司岗位很感兴趣。")
    assert "banned_phrase:HITL" in first_greeting_problems("设计了 hitl 兜底。")
