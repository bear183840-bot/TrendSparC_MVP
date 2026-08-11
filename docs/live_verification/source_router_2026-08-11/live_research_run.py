"""실제 API로 source_router.research()를 끝까지 실행 - entity 연결이 끊긴
이후 상태에서 "롱폼과 숏폼 미디어 소비 트랜드" 질문이 원문을 몇 건이나
확보하는지 확인한다. req_cli_8452ace0(지난 실행)과 동일한 조건으로 재현.
"""
import json
import sys

sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from sources.collectors.source_router.router import research

QUESTION = "지난 5년간 OTT 생태계의 변화 추이 (국내 vs 글로벌 비교)"
PURPOSE_ID = "current_status"
PURPOSE_CONFIDENCE = "high"
AUDIENCE = "external"
AS_OF_DATE = "2026-08-11"

print("[research()] 실제 API 호출 시작 (검색+원문검증 포함, 실제 비용 발생)...", file=sys.stderr)
result = research(
    QUESTION,
    purpose_id=PURPOSE_ID,
    purpose_confidence=PURPOSE_CONFIDENCE,
    audience=AUDIENCE,
    as_of_date=AS_OF_DATE,
)

summary = {
    "stop_reason": result.stop_reason,
    "rounds_completed": result.rounds_completed,
    "search_calls_used": result.search_calls_used,
    "search_budget": result.search_budget,
    "search_budget_basis": result.search_budget_basis,
    "total_results": len(result.results),
    "original_source_count": len([
        r for r in result.results if r.evidence_depth == "original_source"
    ]),
    "original_source_urls": [
        r.url for r in result.results if r.evidence_depth == "original_source"
    ],
    "final_coverage_sufficient": result.final_coverage.sufficient if result.final_coverage else None,
    "final_coverage_reason": result.final_coverage.reason if result.final_coverage else None,
    "final_coverage_missing": result.final_coverage.missing if result.final_coverage else None,
    "final_coverage_rejected_claims": result.final_coverage.rejected_claims if result.final_coverage else None,
    "final_coverage_covered_count": len(result.final_coverage.covered) if result.final_coverage else None,
    "coverage_history_rejected_claims_per_round": [
        d.rejected_claims for d in result.coverage_history
    ],
    "search_plan_queries": [
        {"query": q.query, "priority": q.priority, "query_role": q.query_role}
        for q in result.search_plan.queries
    ],
}

with open("scratchpad/live_research_run_result.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(json.dumps(summary, ensure_ascii=False, indent=2))
