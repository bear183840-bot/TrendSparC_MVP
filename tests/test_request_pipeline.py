from common.contracts import UserRequest
from common.errors import StageStatus
from core.request_pipeline.pipeline import run_pipeline


def _make_request(question: str, **kwargs) -> UserRequest:
    return UserRequest(request_id="req_test_pipeline", question=question, **kwargs)


def test_dry_run_passes_every_stage_with_valid_contracts():
    request = _make_request("SK하이닉스 HBM 시장 전망", target_audience="practitioner")
    result = run_pipeline(request, dry_run=True)

    assert result.halted_at_stage is None
    assert result.intent is not None
    assert result.entities is not None
    assert result.sector_route is not None
    assert result.sector_route.status == "routed"
    assert result.source_plan is not None
    assert result.synthesis is not None
    assert result.report_plan is not None
    assert result.audience_adaptation is not None
    assert result.layout is not None

    statuses = {trace.stage: trace.status for trace in result.trace}
    assert statuses["intent"] == StageStatus.OK
    assert statuses["entity"] == StageStatus.OK
    assert statuses["sector_router"] == StageStatus.OK
    assert statuses["source_planner"] == StageStatus.OK
    assert statuses["synthesis"] == StageStatus.OK
    assert statuses["report_planner"] == StageStatus.OK
    assert statuses["audience_adapter"] == StageStatus.OK
    assert statuses["layout_generator"] == StageStatus.OK
    for role in ("collector", "processor", "validator", "analyzer"):
        assert statuses[f"sector_adapter.{role}"] == StageStatus.SKIPPED

    assert all(trace.status != StageStatus.FAILED for trace in result.trace)


def test_no_sector_specified_falls_back_to_general():
    request = _make_request("오늘 점심 뭐 먹지")
    result = run_pipeline(request, dry_run=True)

    assert result.sector_route.status == "routed"
    assert result.sector_route.sector_id == "general"
