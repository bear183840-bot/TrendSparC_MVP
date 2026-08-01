# SK Planet source registry

SK Planet 섹터의 실행용 Source를 관리한다.

질문마다 등록된 후보 중 관련성 높은 소스를 선별해 쓰는 구조로 전환 중이라, 섹터 전용 Source를 5개에서 **16개**로 확대했다 (2026-08-01, 실제 공개 페이지와 섹션을 확인한 신규 11개만 반영). 공통 네이버 뉴스는 `sources/registry/common/`에서 자동 병합되므로 실제 SourcePlan 기준으로는 **최대 17개 Source**가 후보로 사용된다.

## 현재 등록 Source

| 이름 | role | content_type | reliability_tier | 주요 용도 |
|---|---|---|---|---|
| SK플래닛 공식 뉴스룸 | `official` | `press_release` | `official` | 공식 사업 동향 |
| 전자신문 (IT/데이터/플랫폼) | `search` | `analysis` | `analyst_media` | IT·플랫폼 뉴스 보완 |
| 블로터 (Web3/테크) | `market_analysis` | `analysis` | `analyst_media` | Web3·테크 시장 분석 |
| 모바일인덱스 (아이지에이웍스) | `market_analysis` | `analysis` | `analyst_media` | 앱/트래픽 시장 데이터 |
| 데이터넷 (빅데이터/마케팅) | `search` | `analysis` | `analyst_media` | 데이터·마케팅 동향 |
| 개인정보보호위원회 보도자료 | `regulatory_official` | `press_release` | `official` | 개인정보·마이데이터 정책 1차 출처 |
| 금융위원회 보도자료 | `regulatory_official` | `press_release` | `official` | 금융 마이데이터 규제 1차 출처 |
| 디지털데일리 (IT/플랫폼) | `search` | `analysis` | `analyst_media` | IT·플랫폼 뉴스 보완 |
| 지디넷코리아 (Computing) | `search` | `analysis` | `analyst_media` | 모바일 커머스·마이데이터 뉴스 보완 |
| 매드타임스 (마케팅/애드테크) | `search` | `analysis` | `analyst_media` | Ad-tech·모바일 광고 뉴스 보완 |
| 모비인사이드 (마케팅/플랫폼) | `search` | `analysis` | `analyst_media` | 모바일 마케팅 트렌드 보완 |
| 아이뉴스24 (IT) | `search` | `analysis` | `analyst_media` | IT·데이터 플랫폼 뉴스 보완 |
| 카카오페이 보도자료 | `competitor_official` | `press_release` | `official` | 핀테크·멤버십 경쟁사 공식 동향 |
| 쿠팡 뉴스룸 | `competitor_official` | `press_release` | `official` | 와우 멤버십·커머스 경쟁사 공식 동향 |
| 과학기술정보통신부 보도자료 | `regulatory_official` | `press_release` | `official` | AI·데이터·플랫폼 정책 1차 출처 |
| 나스미디어 정기보고서 | `market_analysis` | `analysis` | `analyst_media` | 디지털 광고·마케팅 시장 분석 |
| 네이버 뉴스 | `search` | - | `common` | 공통 Source, 일반 뉴스 보완 |

## 알려진 gap

- **`competitor_official`은 카카오페이와 쿠팡 2개를 확보했다.** 네이버·롯데멤버스는 정확한 공개 보도자료 목록을 확인하지 못해 등록하지 않았다.
- **`user_sentiment` 역할도 비어 있다.** 구글 플레이스토어(시럽 앱 리뷰)를 후보로 검토했으나, 페이지 자체는 실존해도 동적 렌더링 콘텐츠라 Firecrawl이 리뷰를 안정적으로 스크랩할 수 있을지 확인하지 못해 등록을 보류했다.

### 이번에 확인하지 못한 후보 (2026-08-01)

아래 후보는 공개 수집 가능성을 확정하지 못해 등록하지 않았다:

| 후보 | 상태 |
|---|---|
| 네이버 프레스 (보도자료) | 홈페이지는 실존하나 정확한 보도자료 목록 URL 미확인 |
| 롯데멤버스(L.POINT) 뉴스룸 | 실제 사이트 확인 결과 보도자료/뉴스 섹션 자체가 없음 |
| 오픈서베이 트렌드 리포트 | 현재 카테고리와 개별 글은 확인했으나 직접 반복 수집에서 HTTP 429가 발생해 안정적인 Firecrawl 수집 여부 미확정 |
| 메조미디어 인사이트 | SSL 인증서 오류로 접속 실패 |
| 구글 플레이스토어 (시럽 앱 리뷰) | 페이지 실존 확인, 단 동적 렌더링이라 리뷰 스크랩 가능 여부 미확인 |

## 등록 원칙

- 실제 실행용 Source 정보는 같은 폴더의 `sources.json`을 기준으로 한다.
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않는다.
- SK Planet은 데이터 마케팅, 리워드, 커머스, Ad-Tech 관점의 Source를 우선한다.
- 새로운 Source를 추가할 때는 `role`, `content_type`, `collection_method`, `frequency`, `reliability_reason`을 함께 확인한다.
