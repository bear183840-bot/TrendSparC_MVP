# SK Planet source registry

SK Planet 섹터의 실행용 Source를 관리한다. 현재 전용 Source 5개가 등록되어 있으며, 공통 네이버 뉴스는 `sources/registry/common/`에서 자동 병합된다.

| 이름 | role | content_type | 주요 용도 |
|---|---|---|---|
| SK플래닛 공식 뉴스룸 | `official` | `press_release` | 공식 사업 동향 |
| 전자신문 (IT/데이터/플랫폼) | `search` | `analysis` | IT·플랫폼 뉴스 보완 |
| 블로터 (Web3/테크) | `market_analysis` | `analysis` | Web3·테크 시장 분석 |
| 모바일인덱스 (아이지에이웍스) | `market_analysis` | `analysis` | 앱/트래픽 시장 데이터 |
| 데이터넷 (빅데이터/마케팅) | `search` | `analysis` | 데이터·마케팅 동향 |

## 등록 원칙

- Source 추가/삭제는 README가 아니라 `sources.json`을 기준으로 한다.
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않는다.
- SK Planet은 데이터 마케팅, 리워드, 커머스, Ad-Tech 관점의 Source를 우선한다.
