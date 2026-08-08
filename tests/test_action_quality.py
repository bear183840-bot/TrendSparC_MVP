from common.action_quality import actions_for_owner, is_action_for_owner


def test_third_party_plan_is_evidence_not_target_company_action():
    action = "콘진원은 OTT 산업 진흥 정책 수립에 노력할 예정이다. [doc_id=kocca:1]"
    assert not is_action_for_owner(action, "SK브로드밴드")


def test_owner_named_and_subjectless_proposals_remain_actions():
    assert is_action_for_owner("SK브로드밴드는 콘텐츠 투자를 확대한다.", "SK브로드밴드")
    assert is_action_for_owner("콘텐츠 투자를 확대하는 방안을 검토한다.", "SK브로드밴드")


def test_action_filter_deduplicates_without_losing_citations():
    actions = [
        "요금제를 재설계한다. [doc_id=a:1]",
        "요금제를 재설계한다. [doc_id=a:2]",
        "협회는 지원책을 발표할 예정이다. [doc_id=b:1]",
    ]
    assert actions_for_owner(actions, "SK브로드밴드") == [actions[0]]
