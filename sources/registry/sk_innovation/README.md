# SK Innovation source registry

SK Innovation 섹터의 실행용 Source를 관리한다. 현재 전용 Source 4개가 등록되어 있으며, 공통 네이버 뉴스는 `sources/registry/common/`에서 자동 병합된다.

| 이름 | role | content_type | 주요 용도 |
|---|---|---|---|
| SK이노베이션 공식 뉴스룸 (SKinno News) | `official` | `press_release` | 공식 사업·투자 발표 |
| 전기신문 (배터리·ESS 섹션) | `search` | `analysis` | 배터리·ESS 뉴스 보완 |
| 디일렉 (THE ELEC, 배터리 섹션) | `market_analysis` | `analysis` | 배터리 산업 분석 |
| 이투뉴스 (산업 섹션) | `search` | `analysis` | 정유·가스·신재생 산업 뉴스 보완 |

## 등록 원칙

- 배터리, 정유, 석유화학, 친환경에너지 Source의 균형을 본다.
- 시장분석 Source와 일반 뉴스 Source를 구분해 role을 부여한다.
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않는다.
