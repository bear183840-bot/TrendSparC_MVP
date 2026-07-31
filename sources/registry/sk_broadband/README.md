# SK Broadband source registry

SK Broadband 섹터의 실행용 Source를 관리한다. 현재는 크롤링 부담과 분석 목적을 고려해 **섹터 전용 Source 5개**로 제한한다. 공통 네이버 뉴스는 `sources/registry/common/`에서 자동 병합되므로 실제 SourcePlan 기준으로는 **최대 6개 Source**가 사용된다.

## 현재 등록 Source

| 이름 | role | content_type | 주요 용도 |
|---|---|---|---|
| SK브로드밴드 뉴스룸 | `official` | `press_release` | 공식 사업·서비스 발표 |
| KT 뉴스룸 (경쟁사) | `competitor_official` | `press_release` | 경쟁사 공식 발표 비교 |
| 한국콘텐츠진흥원(KOCCA) | `market_analysis` | `analysis` | 콘텐츠·미디어 산업 통계/시장자료 |
| 전자신문 (통신) | `search` | `analysis` | 통신·미디어 뉴스 보완 |
| 왓챠피디아 | `user_sentiment` | - | 콘텐츠/OTT 사용자 반응 참고 |
| 네이버 뉴스 | `search` | - | 공통 Source, 일반 뉴스 보완 |

## Source 선정 이유

### SK브로드밴드 뉴스룸

- SK브로드밴드의 서비스, 기술, 제휴 관련 공식 1차 자료
- 신규 서비스, AI 적용 사례, 사업 방향 등 산업동향 분석에 활용

### KT 뉴스룸

- IPTV·통신·미디어 영역의 주요 경쟁사 공식 발표 확인
- 경쟁사 서비스 출시, 투자, 제휴 동향 비교에 활용

### 한국콘텐츠진흥원(KOCCA)

- 콘텐츠 산업 통계와 시장 자료를 제공하는 공공기관
- 콘텐츠·미디어 시장 규모와 이용자 현황 분석에 활용
- 규제기관이라기보다는 `market_analysis` 성격으로 분류

### 전자신문 (통신)

- 통신·미디어 산업의 주요 뉴스와 해설 기사 보완
- 공식 발표만으로 부족한 시장 반응과 산업 맥락 확인에 활용

### 왓챠피디아

- OTT·콘텐츠 소비자의 반응과 관심도를 참고하기 위한 user sentiment Source
- 정량 신뢰도 판단보다는 보조적 사용자 반응 확인 목적으로 활용

### 네이버 뉴스

- 모든 섹터에 공통으로 병합되는 일반 뉴스 Source
- 전용 Source에서 놓칠 수 있는 기사 보완용으로 사용

## 향후 검토 Source

기존 후보였던 방송통신위원회(KCC), 정보통신정책연구원(KISDI)은 정책·규제·통신시장 분석에 의미가 있으므로 후보로 보존한다. 현재 실행용 `sources.json`에는 등록하지 않았으며, 팀 회의에서 실제 수집 범위가 확정되면 추가 여부를 결정한다.

## 등록 원칙

- 실제 실행용 Source 정보는 같은 폴더의 `sources.json`에 등록한다.
- Source 수를 무작정 늘리지 않고, 공식성·시장분석·뉴스 보완·사용자 반응 역할이 겹치지 않게 관리한다.
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않는다.
- 새로운 Source를 추가할 때는 `role`, `content_type`, `collection_method`, `frequency`, `reliability_reason`을 함께 확인한다.
