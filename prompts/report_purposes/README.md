# Report Purpose Prompts

이 폴더는 질문 목적별 Report Purpose Prompt를 관리한다.

현재 목적 유형은 멘토 피드백 기준으로 4개다.

| purpose_id | 한국어 | 목적 |
|---|---|---|
| `current_status` | 현황 파악 | 현재 상황, 시장 상태, 향후 전망 |
| `issue_response` | 이슈 대응 | 이슈, 영향, 대응 방안 |
| `future_business` | 미래사업 | 트렌드, 투자, 추천 전략 |
| `root_cause` | 문제 분석 | 원인, 영향, 개선 방안 |

## 원칙

- 이 폴더의 Prompt는 런타임 분석/보고서 구조에 영향을 주는 프로젝트 자산이다.
- `core/report_purpose/classifier.py`는 목적별 파일을 분류 근거로 읽고,
  `core/report_planner/planner.py`는 선택된 목적 파일과 `common_planning.md`를 함께
  읽어 섹션·근거 배치를 계획한다.
- `common_planning.md`는 QUESTION FIRST → DIRECT ANSWER → NARRATIVE → SLOT →
  BLOCK → LAYOUT의 공통 원칙을 담고, 목적별 파일은 각 목적의 스토리 흐름과 정보
  우선순위를 담당한다.
- 목적 프롬프트의 block 힌트는 필요한 데이터 모양을 수집하도록 돕지만 최종 렌더링을
  강제하지 않는다. 최종 블록 적격성은 `common/block_shapes.py`가 판정한다.
- 프롬프트 규칙을 바꾸면 `tests/test_prompt_invariants.py`의 불변식도 함께 갱신한다.
- 기존 `prompts/report_structures/`는 호환용으로 보존하지만, 새 작업은 이 폴더를 기준으로 한다.
