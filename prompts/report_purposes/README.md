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
- 팀원들이 작성할 때는 각 목적별로 필요한 섹션, 중요도 기준, 대시보드 블록 힌트, 1-page report 구성 기준을 명시한다.
- 프롬프트가 아직 비어 있어도 코드는 깨지지 않아야 한다.
- 기존 `prompts/report_structures/`는 호환용으로 보존하지만, 새 작업은 이 폴더를 기준으로 한다.
