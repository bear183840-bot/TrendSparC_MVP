# source_router 라이브 검증 기록 (2026-08-11)

이 폴더는 `source-router-grounding-and-pacing` 브랜치의 변경들을 **실제 API 키로
돌려서** 확인한 산출물이다. 여기 있는 모든 JSON은 실행 결과를 그대로 저장한
것이며, 손으로 편집하지 않았다.

이 기록을 남기는 이유는, 이번 브랜치에서 고친 문제 중 상당수가 **단위 테스트로는
보이지 않는 것**이기 때문이다. 코드가 무엇을 하는지가 아니라 모델이 실제로 무엇을
반환하는지에 대한 문제라, 근거가 실행 결과 자체에만 있다.

**주의: 이 파일들은 특정 시점의 스냅샷이다.** 코드가 바뀌면 같은 질문도 다른 결과를
낸다. 현재 동작의 근거로 쓰지 말고, "그때 이런 일이 있었다"는 기록으로만 읽을 것.

## 실행 순서와 각 파일이 보여주는 것

시간순이다. 앞의 실행에서 발견한 문제를 고친 뒤 다음 실행을 돌린 구조라, 파일 간
차이가 곧 각 수정의 효과다.

| 시각 | 파일 | 질문 | 무엇을 보여주는가 |
|---|---|---|---|
| 12:31 | `query_gen_inspect.json` | 롱폼/숏폼 | entity 단계가 만든 entities / source_plan / collection_events. 라우터가 entity에서 무엇을 받고 있었는지의 기록 |
| 12:31 | `router_trace.json` | 롱폼/숏폼 | 전체 트레이스(49KB). `stop_reason=search_call_budget_exhausted`, 검색 호출 **6회**로 예산 소진 — 예산 상향 이전 상태 |
| 12:44 | `query_gen_only_result_utf8.json` | 롱폼/숏폼 | 쿼리 생성만 실행(검색 없음). **"2024" 버그의 직접 증거**: 2026년에 실행했는데 생성된 쿼리가 `"롱폼 미디어" 이용자 수 및 성장률 2024`. `evidence_needs` / `refinement` 키가 남아 있는 것도 이 시점이 entity 연결 제거 이전이었음을 보여준다 |
| 14:46 | `live_research_run_result_before_sufficiency_fix.json` | 롱폼/숏폼 | 원문 4건, `stop_reason=gap_loop_iterations_exhausted`, `sufficient=false`. sufficiency 자기모순 수정 이전 |
| 14:51 | `live_research_run_result_longform_shortform_v3_timeout.json` | 롱폼/숏폼 | 원문 **0건**인데 `sufficient=true`로 종료. 검색 호출 4회(타임아웃으로 소진). 근거 없이 충분하다고 판정하던 문제 |
| 15:08 | `live_research_run_result_before_eager_inspect_fix.json` | OTT | 원문 **0건**, 그런데 `sufficient=true`. `original_source_urls`가 빈 배열이다. eager 원문검사 도입 직전의 같은 질문 기준선 |
| 16:01 | `live_research_run_result.json` | OTT | 원문 **5건** 확보. `coverage_history_rejected_claims_per_round`에 라운드 간 피드백이 실제로 동작한 흔적이 남아 있다(2라운드에서 근거 URL 없는 Gen Z 통계를 거부 → 3라운드에서 재등장하지 않음) |

### 핵심 비교

같은 OTT 질문에 대해 **원문 0건 → 5건**(15:08 대비 16:01). 이 두 파일이 eager
원문검사(`max_auto_inspect_direct_results`)의 효과를 보여주는 직접 근거다.

## 함께 둔 스크립트

- `live_research_run.py` — 위 `live_research_run_result*.json`을 만든 스크립트.
  실제 API를 호출하므로 **비용이 발생한다**. 질문/purpose/audience/as_of_date는
  파일 상단 상수로 되어 있다.
- `max_original_sources_probe.py` — 네트워크를 쓰지 않는다. planner/web_search/
  coverage/extract_html을 전부 성공하도록 페이크로 바꿔서, 라우터가 최상의 경우
  원문을 몇 건까지 낼 수 있는지 확인한다. 현재 설정에서 답은 **15건**이고, 그
  병목은 `max_sources_to_inspect`가 아니라 `max_results`다(원문 수가
  `max_results`에 도달하면 `_cap_results()`가 새 검색 결과를 풀에 못 들어오게
  해서, 검사할 후보 자체가 더 생기지 않는다).

## 여기 없는 것

- `scratchpad/query_gen_only.py` — `query_gen_only_result_utf8.json`을 만든
  스크립트지만, 삭제된 `refiner` 모듈을 import하므로 지금은 실행되지 않는다.
  출력 JSON만 위에 포함했다.
- 이전 세션(2026-08-05 / 08-09 / 08-10)의 `scratchpad/` 산출물들. 이 브랜치의
  작업 범위가 아니라 그대로 두었다.

## 확인한 것

커밋 전에 API 키 패턴(`sk-`, `up_`, `fc-`, `api_key`, `Bearer`, `Authorization`)을
전수 스캔했고 매치 없음을 확인했다. 모든 JSON은 UTF-8로 파싱된다.
