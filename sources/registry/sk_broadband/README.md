# SK Broadband Source Registry

SK Broadband 섹터의 실행용 Source를 관리한다. 이 섹터는 1차 발표 기준 섹터이므로, 단순 뉴스 포털만 쓰지 않고 공식 발표, 경쟁사 공식 자료, 공공 시장 보고서, 산업 전문 매체, 사용자 반응을 함께 본다.

현재는 크롤링 부담과 분석 목적을 고려해 **섹터 전용 Source 6개**로 제한한다. 공통 네이버 뉴스는 `sources/registry/common/`에서 자동 병합되므로 실제 SourcePlan 기준으로는 **최대 7개 Source**가 사용된다.

## 현재 등록 Source

| 이름 | role | content_type | reliability_tier | 주요 용도 |
|---|---|---|---|---|
| SK브로드밴드 뉴스룸 | `official` | `press_release` | `official` | 공식 사업·서비스 발표 |
| KT 뉴스룸 | `competitor_official` | `press_release` | `official` | 경쟁사 공식 발표 비교 |
| 한국콘텐츠진흥원(KOCCA) | `market_analysis` | `analysis` | `official` | 콘텐츠·미디어 산업 통계/시장자료 |
| 영화진흥위원회(KOFIC) | `market_analysis` | `analysis` | `official` | 영화산업 결산·콘텐츠 소비 흐름 |
| 전자신문(통신) | `search` | `analysis` | `analyst_media` | 통신·미디어 뉴스 보완 |
| 왓챠피디아 | `user_sentiment` | `review` | `user_generated` | 콘텐츠/OTT 사용자 반응 참고 |
| 네이버 뉴스 | `search` | - | `common` | 공통 Source, 일반 뉴스 보완 |

## Source 선정 이유

### SK브로드밴드 뉴스룸

- SK브로드밴드의 서비스, 기술, 제휴 관련 공식 1차 자료
- 신규 서비스, AI 적용 사례, 사업 방향 등 산업동향 분석에 활용
- 기업 공식 자료이므로 사실 확인의 기준점으로 사용

### KT 뉴스룸

- IPTV·통신·미디어 영역의 주요 경쟁사 공식 발표 확인
- 경쟁사 서비스 출시, 투자, 제휴 동향 비교에 활용
- SK브로드밴드 전략기획 관점에서 경쟁사 움직임을 빠르게 파악하는 역할

### 한국콘텐츠진흥원(KOCCA)

- 콘텐츠 산업 통계와 시장 자료를 제공하는 공공기관
- 콘텐츠·미디어 시장 규모와 이용자 현황 분석에 활용
- 규제기관이라기보다는 `market_analysis` 성격으로 분류

### 영화진흥위원회(KOFIC)

- 영화산업 결산, 영화관 입장권 통합전산망, 산업 통계 PDF 자료를 제공하는 공공기관
- IPTV·OTT·B tv 콘텐츠 소비 흐름과 영화/영상 콘텐츠 시장 변화를 보는 보조 Source
- 웹 상세 페이지에서 PDF 다운로드 파라미터를 추출한 뒤 Firecrawl parse로 본문을 수집한다.

### 전자신문(통신)

- 통신·미디어 산업의 주요 뉴스와 해설 기사 보완
- 공식 발표만으로 부족한 시장 반응과 산업 맥락 확인에 활용
- 단, 일반 뉴스이므로 공식 Source와 Cross Check가 필요하다.

### 왓챠피디아

- OTT·콘텐츠 소비자의 반응과 관심도를 참고하기 위한 user sentiment Source
- 정량 신뢰도 판단보다는 보조적 사용자 반응 확인 목적으로 활용
- 사용자 리뷰 데이터는 대표성 한계가 있으므로 단독 근거로 사용하지 않는다.

### 네이버 뉴스

- 모든 섹터에 공통으로 병합되는 일반 뉴스 Source
- 전용 Source에서 놓칠 수 있는 기사 보완용으로 사용
- 공통 Source이므로 SK Broadband 전용 Source 수에는 포함하지 않는다.

## KOFIC 수집 방식

KOFIC는 PDF 자료가 많아 일반 HTML 크롤링만으로는 본문을 안정적으로 확보하기 어렵다. 따라서 별도 helper를 사용한다.

1. Firecrawl 또는 목록 페이지에서 KOFIC 상세 URL 탐색
2. 상세 HTML의 `fn_fileDownload(...)` 파라미터 추출
3. KOFIC 공식 다운로드 endpoint에 POST 요청
4. PDF bytes 여부 확인
5. Firecrawl parse로 PDF 본문을 markdown으로 변환

PDF 전용 로직은 `sources/collectors/kofic_pdf.py`에 분리되어 있으며, 브로드밴드 adapter는 해당 helper만 호출한다.

## 향후 검토 Source

기존 후보였던 방송통신위원회(KCC), 정보통신정책연구원(KISDI)은 정책·규제·통신시장 분석에 의미가 있으므로 후보로 보존한다. 현재 실행용 `sources.json`에는 등록하지 않았으며, 팀 회의에서 실제 수집 범위가 확정되면 추가 여부를 결정한다.

## 등록 원칙

- 실제 실행용 Source 정보는 같은 폴더의 `sources.json`에 등록한다.
- Source 수를 무작정 늘리지 않고, 공식성·시장분석·뉴스 보완·사용자 반응 역할이 겹치지 않게 관리한다.
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않는다.
- 새로운 Source를 추가할 때는 `role`, `content_type`, `collection_method`, `frequency`, `reliability_reason`을 함께 확인한다.
- 사용자 반응 Source는 보조 신호로만 사용하고, 공식·시장분석 Source와 Cross Check한다.
