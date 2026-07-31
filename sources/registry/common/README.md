# Common source registry

모든 섹터의 `SourcePlan`에 자동 병합되는 공통 Source를 관리한다.

## 현재 등록 Source

| 이름 | role | 용도 |
|---|---|---|
| 네이버 뉴스 | `search` | 섹터별 전용 Source에서 놓칠 수 있는 일반 뉴스 보완 |

## 사용 원칙

- 특정 계열사 전용 Source는 `sources/registry/<sector_id>/`에 둔다.
- 모든 섹터에서 공통으로 쓸 수 있는 Source만 여기에 둔다.
- 공통 Source는 섹터별 Source 개수 산정에 포함된다.
- 예: SK Broadband는 전용 5개 + 공통 네이버 1개 = SourcePlan 최대 6개.
