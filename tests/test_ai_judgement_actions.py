from common.contracts import SynthesisClaim, TrendSynthesis
from core.synthesis.ai_based import _validated_inferred_actions
from reporting.dashboard_streamlit import components


def _synthesis():
    return TrendSynthesis(
        request_id="req_ai_action",
        sector_id="sk_broadband",
        grounded_claims=[
            SynthesisClaim(
                synthesis_claim_id="doc:claim-1",
                claim_id="claim-1",
                claim_type="factor",
                claim="20대의 숏폼 이용률이 높다.",
                evidence_quote="20대의 숏폼 이용률이 높다.",
                confidence="high",
                doc_id="doc",
                source_id="source",
                source_url="https://example.com/evidence",
            )
        ],
    )


def test_ai_action_requires_real_verified_claim_ids_and_a_written_basis():
    synthesis = _synthesis()
    actions = _validated_inferred_actions([
        {
            "action": "20대 캠페인에서 숏폼 매체를 우선 검토한다.",
            "basis": "검증된 20대 이용 행태 근거에 따른 우선순위 판단",
            "supporting_claim_ids": ["doc:claim-1"],
            "confidence": "medium",
        },
        {
            "action": "근거 없는 행동",
            "basis": "근거 없음",
            "supporting_claim_ids": ["unknown"],
            "confidence": "high",
        },
    ], synthesis)

    assert len(actions) == 1
    assert actions[0].supporting_claim_ids == ["doc:claim-1"]


def test_ai_action_without_basis_is_discarded():
    assert _validated_inferred_actions([
        {
            "action": "숏폼을 쓴다.",
            "basis": "",
            "supporting_claim_ids": ["doc:claim-1"],
            "confidence": "medium",
        }
    ], _synthesis()) == []


def test_action_renderer_labels_ai_judgement_and_prints_its_basis(monkeypatch):
    captured = []
    monkeypatch.setattr(
        components.st, "markdown", lambda body, **kwargs: captured.append(body)
    )

    components.render_action_list(
        [("숏폼 매체를 우선 검토한다.", "", "https://example.com/evidence")],
        owner="SK브로드밴드",
        ai_judgements={"숏폼 매체를 우선 검토한다.": "20대 이용 행태 근거를 종합한 판단"},
    )

    output = "\n".join(captured)
    assert "AI 판단" in output
    assert "판단 근거" in output
    assert "20대 이용 행태 근거를 종합한 판단" in output
