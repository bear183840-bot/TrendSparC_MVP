# SK hynix source registry

SK hynix 섹터의 실행용 Source를 관리한다.

질문마다 등록된 후보 중 관련성 높은 소스를 선별해 쓰는 구조로 전환 중이라, 섹터 전용 Source를 5개에서 **14개**로 확대했다 (2026-08-01, 신규 15개 후보 중 실제 접속 검증을 통과한 9개만 반영 — 검증 결과는 아래 "이번에 반려된 후보" 참고). 공통 네이버 뉴스는 `sources/registry/common/`에서 자동 병합되므로 실제 SourcePlan 기준으로는 **최대 15개 Source**가 후보로 사용된다.

## 현재 등록 Source

| 이름 | role | content_type | reliability_tier | 주요 용도 |
|---|---|---|---|---|
| SK하이닉스 뉴스룸 | `official` | `press_release` | `official` | 공식 투자·실적 발표 |
| 삼성전자DS 뉴스룸 | `competitor_official` | `press_release` | `official` | 최대 경쟁사 공식 발표 비교 |
| 전자신문(반도체) | `search` | `analysis` | `analyst_media` | 반도체 산업 동향 보완 |
| TrendForce Press Center | `market_analysis` | `analysis` | `analyst_media` | DRAM/NAND/HBM 가격·수급 데이터 |
| BIS (미국 상무부 산업안보국) Newsroom | `regulatory_official` | `press_release` | - | 대중국 수출통제 등 규제 1차 출처 |
| TSMC Newsroom | `competitor_official` | `press_release` | `official` | 파운드리·패키징(CoWoS) 공급 동향 |
| NVIDIA Newsroom | `competitor_official` | `press_release` | `official` | HBM 최대 고객사 동향 |
| 디일렉 (반도체) | `search` | `analysis` | `analyst_media` | 반도체 팹 증설·CAPEX 보완 |
| 디지털데일리 (반도체/디스플레이) | `search` | `analysis` | `analyst_media` | 메모리 반도체 뉴스 보완 |
| 지디넷코리아 (반도체/디스플레이) | `search` | `analysis` | `analyst_media` | 반도체/디스플레이 뉴스 보완 |
| 아이뉴스24 (IT) | `search` | `analysis` | `analyst_media` | 종합 IT 뉴스 보완 |
| 산업통상자원부 보도자료 | `regulatory_official` | `press_release` | `official` | 반도체 산업 정책·보조금 1차 출처 |
| 카운터포인트리서치 (반도체) | `market_analysis` | `analysis` | `analyst_media` | 글로벌 D램·SoC 시장 데이터 |
| SK하이닉스 IR 자료실 | `official` | `press_release` | `official` | 실적 발표·가이던스·CAPEX |
| 네이버 뉴스 | `search` | - | `common` | 공통 Source, 일반 뉴스 보완 |

## Source 선정 이유

### TSMC Newsroom / NVIDIA Newsroom

- 파운드리·패키징(TSMC CoWoS)과 HBM 최대 고객사(NVIDIA)의 공식 발표를 확인해 SK하이닉스 사업에 미치는 영향을 판단하기 위한 자료
- 기존 경쟁사 공식 자료(삼성전자DS)와 함께 `competitor_official` 역할이지만, 경쟁 관계가 아니라 공급망·고객사 관계 관점의 소스임 — role 자체는 편의상 동일하게 분류

### 디일렉 / 디지털데일리 / 지디넷코리아 / 아이뉴스24

- 전자신문 외에 반도체·IT 뉴스를 보완할 전문매체 추가 (검색 후보 다양화)
- 아이뉴스24는 반도체 전용 매체는 아니고 종합 IT 매체이나, 반도체 가격·실적 기사도 다수 포함돼 있어 `search` 역할로 등록
- 모두 공식 발표만으로 부족한 시장 반응·산업 맥락 확인용, 공식 Source와 Cross Check 필요

### 산업통상자원부 보도자료

- 반도체 보조금·수출 규제 등 정책 리스크를 확인하는 정부 공식 1차 출처
- 기존 BIS(미국)와 함께 국내 정책까지 커버하도록 `regulatory_official` 역할 보강

### 카운터포인트리서치 (반도체)

- 파운드리·메모리·스마트폰 SoC를 트래킹하는 시장조사 전문기관, TrendForce 외 두 번째 `market_analysis` 소스
- TrendForce와 마찬가지로 시장을 해석·트래킹하는 기관이라 `analyst_media`로 분류 (공식 1차 발표가 아니므로 `official` 아님)

### SK하이닉스 IR 자료실

- 실적 발표·가이던스·CAPEX 등 뉴스룸과는 별도로 관리되는 IR 전용 카테고리
- 기존 SK하이닉스 뉴스룸과 함께 `official` 역할 2개(쿼터 상한)를 채움

### 네이버 뉴스

- 모든 섹터에 공통으로 병합되는 일반 뉴스 Source
- 전용 Source에서 놓칠 수 있는 기사 보완용으로 사용
- 공통 Source이므로 SK hynix 전용 Source 수에는 포함하지 않는다.

### 이번에 반려된 후보 (2026-08-01 검증)

신규 후보 15개 중 아래 6개는 실제 접속 검증에서 탈락해 등록하지 않았다 — 다음에 이 소스들을 다시 검토할 때 참고할 것:

| 후보 | 문제 |
|---|---|
| Micron Newsroom | 브라우징 도구가 3회 모두 타임아웃 — 사이트가 죽었다고 확정할 순 없으나 이번엔 확인 불가로 처리 |
| EE Times (Semiconductors) | 브라우징 도구가 2회 모두 타임아웃 — 확인 불가 |
| Bloomberg Technology | 접속 시 403 Forbidden — 페이월/봇 차단으로 추정 |
| 미국 반도체산업협회(SIA) News | 접속 시 403 Forbidden — 접근 차단 |
| Omdia Research (Semiconductor) | 접속 시 403 Forbidden — 구독 서비스로 접근 차단 |
| IDC 뉴스룸 | my.idc.com으로 리다이렉트된 뒤 403 Forbidden — 접근 차단 |

## 등록 원칙

- 실제 실행용 Source 정보는 같은 폴더의 `sources.json`에 등록한다.
- Source 수를 무작정 늘리지 않고, 공식성·시장분석·뉴스 보완·규제 역할이 겹치지 않게 관리한다.
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않는다.
- 새로운 Source를 추가할 때는 `role`, `content_type`, `collection_method`, `frequency`, `reliability_reason`을 함께 확인한다.
