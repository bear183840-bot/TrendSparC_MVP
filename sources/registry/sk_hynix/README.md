# SK hynix source registry

SK hynix 섹터의 실행용 Source를 관리한다. 현재 전용 Source 5개가 등록되어 있으며, 공통 네이버 뉴스는 `sources/registry/common/`에서 자동 병합된다.

| 이름 | role | content_type | 수집 방식 | 갱신 주기 |
|---|---|---|---|---|
| SK하이닉스 뉴스룸 | `official` | `press_release` | rss, crawling | daily |
| 삼성전자DS 뉴스룸 | `competitor_official` | `press_release` | rss, crawling | daily |
| 전자신문(반도체) | `search` | `analysis` | rss | daily |
| TrendForce Press Center | `market_analysis` | `analysis` | rss, crawling | daily |
| BIS 미국 상무부 산업안보국 Newsroom | `regulatory_official` | `press_release` | crawling | new_filings_only |

## 등록 원칙

- 실제 실행용 Source 정보는 같은 폴더의 `sources.json`을 기준으로 한다.
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않는다.
- 새로운 Source를 추가할 때는 `role`, `content_type`, `collection_method`, `frequency`, `reliability_reason`을 함께 확인한다.
