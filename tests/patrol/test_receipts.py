# ruff: noqa: RUF001  -- Chinese chat previews carry full-width punctuation by design.
from datetime import UTC, datetime

from jobagent.patrol.receipts import match_conversation, receipt_status, receipts_from_snapshot
from jobagent.schemas.conversation import Conversation
from jobagent.schemas.patrol import PatrolSnapshot, SnapshotItem
from jobagent.schemas.sources import ObservabilitySpec

AT = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
BOSS = ObservabilitySpec(read_markers=["[已读]"], delivered_markers=["[送达]"])


def item(
    company: str,
    preview: str,
    *,
    last_from: str = "us",
    title: str | None = None,
    our_status: str = "unknown",
) -> SnapshotItem:
    return SnapshotItem(
        key=f"王女士|{company}",
        recruiter="王女士",
        company=company,
        title=title,
        preview=preview,
        last_from=last_from,  # type: ignore[arg-type]
        our_status=our_status,  # type: ignore[arg-type]
    )


def conversation(conversation_id: str, company: str, title: str = "AI产品经理") -> Conversation:
    return Conversation(
        conversation_id=conversation_id,
        platform="boss",
        company=company,
        title=title,
        origin="outreach",
        opened_at=AT,
    )


def test_the_status_word_before_our_last_message_is_the_receipt() -> None:
    assert receipt_status(item("甲公司", "[已读]您好，我是Joshua"), BOSS) == "read"
    assert receipt_status(item("甲公司", "[送达]您好，我是Joshua"), BOSS) == "delivered"
    assert receipt_status(item("甲公司", "您好，我是Joshua"), BOSS) is None


def test_a_status_word_in_their_message_is_not_a_receipt_for_ours() -> None:
    assert receipt_status(item("甲公司", "[已读]哈哈", last_from="them"), BOSS) is None


def test_a_board_without_read_markers_never_yields_a_read_receipt() -> None:
    zhaopin = ObservabilitySpec(delivered_markers=["[送达]"])

    assert receipt_status(item("甲公司", "[已读]您好"), zhaopin) is None
    assert receipt_status(item("甲公司", "[送达]您好"), zhaopin) == "delivered"
    assert receipt_status(item("甲公司", "[已读]您好"), None) is None


def test_a_status_the_host_read_off_the_page_wins_over_the_preview() -> None:
    assert receipt_status(item("甲公司", "您好", our_status="read"), BOSS) == "read"


def test_snapshot_rows_match_conversations_by_normalised_company() -> None:
    conversations = [
        conversation("CONV_A", "猎头(上海甲科技有限公司)"),
        conversation("CONV_B", "乙公司(王女士)"),
    ]

    assert match_conversation(item("上海甲科技有限公司", "x"), "boss", conversations) == (
        "CONV_A",
        None,
    )
    # Boards append the recruiter's role to the company line.
    assert match_conversation(item("乙公司HR", "x"), "boss", conversations) == ("CONV_B", None)
    assert match_conversation(item("丙公司", "x"), "boss", conversations) == (None, "no_match")
    assert match_conversation(item("乙公司", "x"), "liepin", conversations) == (None, "no_match")


def test_two_conversations_with_one_company_need_the_title_to_tell_apart() -> None:
    conversations = [
        conversation("CONV_A", "甲公司", "AI产品经理"),
        conversation("CONV_B", "甲公司", "数据产品经理"),
    ]

    assert match_conversation(item("甲公司", "x"), "boss", conversations) == (None, "ambiguous")
    assert match_conversation(item("甲公司", "x", title="数据产品经理"), "boss", conversations) == (
        "CONV_B",
        None,
    )


def test_a_role_before_a_middle_dot_is_not_part_of_the_company() -> None:
    conversations = [
        conversation("CONV_A", "云从科技"),
        conversation("CONV_B", "猎头(深圳市博睿思管理咨询有限公司)"),
        conversation("CONV_C", "成都新大瀚人力资源管理有限公司(猎头)"),
    ]

    assert match_conversation(item("招聘·云从科技", "x"), "boss", conversations) == ("CONV_A", None)
    assert match_conversation(
        item("资深猎头顾问·深圳市博睿思管理咨询有限公司", "x"), "boss", conversations
    ) == ("CONV_B", None)
    assert match_conversation(
        item("猎头顾问/助理·成都新大瀚人力资源管理有限公司", "x"), "boss", conversations
    ) == ("CONV_C", None)
    # Whatever stands before the dot, the company after it must still be a known one.
    assert match_conversation(item("招聘·丙公司", "x"), "boss", conversations) == (
        None,
        "no_match",
    )


def test_the_whole_name_wins_over_the_part_after_a_middle_dot() -> None:
    conversations = [conversation("CONV_A", "甲·乙科技"), conversation("CONV_B", "乙科技")]

    assert match_conversation(item("甲·乙科技", "x"), "boss", conversations) == ("CONV_A", None)


def test_a_region_note_inside_the_name_and_notes_after_a_comma_are_dropped() -> None:
    conversations = [
        conversation("CONV_A", "猎头(晴聘(石家庄)网络科技有限公司)"),
        conversation("CONV_B", "猎头(上海瀚辉人力资源咨询服务有限公司,客户 Firmior)"),
        conversation("CONV_C", "凯德永驰(猎头,客户:某大型互联网公司)"),
    ]

    assert match_conversation(item("晴聘(石家庄)网络科技有限公司", "x"), "boss", conversations) == (
        "CONV_A",
        None,
    )
    assert match_conversation(
        item("上海瀚辉人力资源咨询服务有限公司", "x"), "boss", conversations
    ) == ("CONV_B", None)
    assert match_conversation(item("凯德永驰", "x"), "boss", conversations) == ("CONV_C", None)


def test_role_words_stuck_to_the_company_are_dropped() -> None:
    conversations = [conversation("CONV_A", "九方智投"), conversation("CONV_B", "凯德永驰")]

    assert match_conversation(item("九方智投招聘专家", "x"), "boss", conversations) == (
        "CONV_A",
        None,
    )
    assert match_conversation(item("凯德永驰猎头顾问", "x"), "boss", conversations) == (
        "CONV_B",
        None,
    )


def test_a_headhunter_named_in_the_note_of_an_anonymous_client_is_the_row_company() -> None:
    conversations = [
        conversation("CONV_A", "某人工智能公司(猎头:猎猫猫)"),
        conversation("CONV_B", "某财富管理公司(猎头：南京爱贤进，客户保密)"),
    ]

    assert match_conversation(item("猎猫猫", "x"), "boss", conversations) == ("CONV_A", None)
    assert match_conversation(item("南京爱贤进", "x"), "boss", conversations) == ("CONV_B", None)
    # The client's own name still matches as before.
    assert match_conversation(item("某人工智能公司", "x"), "boss", conversations) == (
        "CONV_A",
        None,
    )
    # A note that only mentions the word is not a name.
    assert match_conversation(item("客户保密", "x"), "boss", conversations) == (None, "no_match")


def test_a_brand_matches_its_legal_name_only_when_nothing_closer_exists() -> None:
    legal = conversation("CONV_A", "上海畅商亨霖信息技术有限公司")

    assert match_conversation(item("上海畅商亨霖", "x"), "boss", [legal]) == ("CONV_A", None)
    # Two different tails on one stem are two companies, not a brand and its legal name.
    assert match_conversation(item("上海畅商亨霖网络科技", "x"), "boss", [legal]) == (
        None,
        "no_match",
    )
    # An exact name is never overridden by a looser one.
    exact = conversation("CONV_B", "上海畅商亨霖")
    assert match_conversation(item("上海畅商亨霖", "x"), "boss", [legal, exact]) == ("CONV_B", None)
    # Two different legal names behind one brand are a person's call.
    other = conversation("CONV_C", "上海畅商亨霖网络科技有限公司")
    assert match_conversation(item("上海畅商亨霖", "x"), "boss", [legal, other]) == (
        None,
        "ambiguous",
    )
    # A brand is not a prefix of just any longer name.
    assert match_conversation(
        item("上海畅商", "x"), "boss", [conversation("CONV_D", "上海畅商亨霖")]
    ) == (None, "no_match")


def test_a_title_cut_short_by_the_board_matches_the_one_title_it_starts() -> None:
    conversations = [
        conversation("CONV_A", "乙公司", "股权投资管理经理/高级经理（成员机构管理方向）"),
        conversation("CONV_B", "乙公司", "股权投资管理经理/高级经理"),
    ]

    assert match_conversation(
        item("乙公司", "x", title="股权投资管理经理/高级经理（"), "boss", conversations
    ) == ("CONV_A", None)
    assert match_conversation(
        item("乙公司", "x", title="股权投资管理经理/高级经理（成员机…"), "boss", conversations
    ) == ("CONV_A", None)
    # A stored title cut short the same way.
    cut = [
        conversation("CONV_C", "乙公司", "AI产品专家-投递通道(方向较多"),
        conversation("CONV_D", "乙公司", "数据产品经理"),
    ]
    assert match_conversation(
        item("乙公司", "x", title="AI产品专家-投递通道(方向较多，杭州)"), "boss", cut
    ) == ("CONV_C", None)


def test_a_title_that_merely_begins_another_is_not_a_match() -> None:
    conversations = [
        conversation("CONV_A", "乙公司", "AI产品经理(金融)"),
        conversation("CONV_B", "乙公司", "数据产品经理"),
    ]

    assert match_conversation(item("乙公司", "x", title="AI产品经理"), "boss", conversations) == (
        None,
        "ambiguous",
    )


def test_a_title_cut_short_that_starts_two_titles_stays_ambiguous() -> None:
    conversations = [
        conversation("CONV_A", "乙公司", "产品经理（北京）"),
        conversation("CONV_B", "乙公司", "产品经理（上海）"),
    ]

    assert match_conversation(item("乙公司", "x", title="产品经理（"), "boss", conversations) == (
        None,
        "ambiguous",
    )


def test_a_recruiter_role_in_the_title_slot_leaves_the_company_ambiguous_not_unknown() -> None:
    conversations = [
        conversation("CONV_A", "甲公司", "AI产品经理"),
        conversation("CONV_B", "甲公司", "数据产品经理"),
    ]

    assert match_conversation(item("甲公司", "x", title="HR"), "boss", conversations) == (
        None,
        "ambiguous",
    )


def test_a_snapshot_yields_receipts_and_lists_rows_it_could_not_place() -> None:
    snapshot = PatrolSnapshot(
        snapshot_id="PSNAP_A",
        platform="boss",
        captured_at=AT,
        items=[
            item("甲公司", "[已读]您好"),
            item("丙公司", "[送达]您好"),
            item("乙公司", "方便发份简历吗", last_from="them"),
        ],
    )
    report = receipts_from_snapshot(
        snapshot, [conversation("CONV_A", "甲公司"), conversation("CONV_B", "乙公司")], BOSS
    )

    assert [(r.conversation_id, r.status, r.snapshot_id) for r in report.receipts] == [
        ("CONV_A", "read", "PSNAP_A")
    ]
    assert report.receipts[0].observed_at == AT
    assert [(u.key, u.status, u.reason) for u in report.unmatched] == [
        ("王女士|丙公司", "delivered", "no_match")
    ]
