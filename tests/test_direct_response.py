from common.contracts import UserRequest
from core.request_pipeline.pipeline import run_pipeline


def test_greeting_returns_short_answer_without_report_pipeline():
    result = run_pipeline(UserRequest(request_id="req_hi", question="안녕!!"), dry_run=False)

    assert result.direct_answer == "안녕하세요! 궁금한 시장·기술·사업 이슈를 편하게 물어보세요."
    assert result.sector_route is None
    assert result.generated_report is None
    assert [trace.stage for trace in result.trace] == ["direct_response"]


def test_real_question_containing_greeting_word_still_runs_pipeline():
    result = run_pipeline(
        UserRequest(request_id="req_not_smalltalk", question="안녕하세요 HBM 개발 현황 알려줘"),
        dry_run=True,
        requested_sector_id="sk_hynix",
    )

    assert result.direct_answer is None
    assert result.sector_route.sector_id == "sk_hynix"
