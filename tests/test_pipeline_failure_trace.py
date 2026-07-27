from common.contracts import UserRequest
from common.errors import StageStatus
from core.request_pipeline.pipeline import run_pipeline


def test_forced_failure_names_the_failing_stage():
    request = UserRequest(request_id="req_test_failure", question="SK하이닉스 HBM 시장 전망")
    result = run_pipeline(request, dry_run=True, force_fail_stage="intent")

    assert result.halted_at_stage == "intent"
    failed_traces = [t for t in result.trace if t.status == StageStatus.FAILED]
    assert len(failed_traces) == 1
    assert failed_traces[0].stage == "intent"
    assert failed_traces[0].reason is not None

    # Downstream stages never ran.
    assert result.entities is None
    assert result.sector_route is None


def test_forced_failure_mid_pipeline_still_names_exact_stage():
    request = UserRequest(request_id="req_test_failure_2", question="SK하이닉스 HBM 시장 전망")
    result = run_pipeline(request, dry_run=True, force_fail_stage="synthesis")

    assert result.halted_at_stage == "synthesis"
    assert result.sector_route is not None
    assert result.source_plan is not None
    assert result.synthesis is None

    failed_traces = [t for t in result.trace if t.status == StageStatus.FAILED]
    assert len(failed_traces) == 1
    assert failed_traces[0].stage == "synthesis"
