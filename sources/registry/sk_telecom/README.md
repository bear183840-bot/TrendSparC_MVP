# SK Telecom source registry

SK Telecom 섹터의 실행용 Source를 관리한다. 현재 전용 Source 4개가 등록되어 있으며, 공통 네이버 뉴스는 `sources/registry/common/`에서 자동 병합된다.

| 이름 | role | content_type | 주요 용도 |
|---|---|---|---|
| SK텔레콤 공식 뉴스룸 | `official` | `press_release` | 공식 사업·기술 발표 |
| 전자신문 (IT·통신 섹션) | `search` | `analysis` | 통신·AI 뉴스 보완 |
| 디지털데일리 (통신/미디어 섹션) | `search` | `analysis` | 통신·미디어 뉴스 보완 |
| 정보통신정책연구원(KISDI) 통신시장 경쟁상황 평가 | `market_analysis` | `analysis` | 통신시장 구조와 경쟁상황 분석 |

## 등록 원칙

- 일반 뉴스 Source만 늘리기보다 공식 발표, 시장분석, 뉴스 보완 역할의 균형을 맞춘다.
- `market_analysis`는 KISDI처럼 통신시장 구조를 설명할 수 있는 자료를 우선한다.
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않는다.
