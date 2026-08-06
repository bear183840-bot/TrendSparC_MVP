# SK Broadband Source Registry

SK Broadband 섹터의 실행용 Source를 관리한다. 이 섹터는 1차 발표 기준 섹터이므로, 단순 뉴스 포털만 쓰지 않고 공식 발표, 경쟁사 공식 자료, 공공 시장 보고서, 산업 전문 매체, 사용자 반응을 함께 본다.

질문마다 등록된 후보 중 관련성 높은 소스를 선별해 쓰는 구조로 전환 중이라, 섹터 전용 Source는 현재 **12개**다 (2026-08-03 기준 — 디지털데일리·키노라이츠 삭제, 미디어통계포털 신규 등록 반영. 이전 검증 결과는 아래 "이번에 반려된 후보" 참고). 공통 네이버 뉴스는 `sources/registry/common/`에서 자동 병합되므로 실제 SourcePlan 기준으로는 **최대 13개 Source**가 후보로 사용된다.

## 현재 등록 Source

| 이름 | role | content_type | reliability_tier | 주요 용도 |
|---|---|---|---|---|
| SK브로드밴드 뉴스룸 | `official` | `press_release` | `official` | 공식 사업·서비스 발표 |
| SK텔레콤 IR 자료실 (SK브로드밴드 연결 실적) | `official` | `analysis` | `official` | 연결 자회사 매출·실적 IR 자료 |
| KT 뉴스룸 | `competitor_official` | `press_release` | `official` | 경쟁사 공식 발표 비교 |
| 한국콘텐츠진흥원(KOCCA) | `market_analysis` | `analysis` | `official` | 콘텐츠·미디어 산업 통계/시장자료 |
| 영화진흥위원회(KOFIC) | `market_analysis` | `analysis` | `official` | 영화산업 결산·SK브로드밴드 IPTV VOD 이용 통계(VKOBIS 연동) |
| 전자신문(통신) | `search` | `analysis` | `analyst_media` | 통신·미디어 뉴스 보완 |
| 왓챠피디아 | `user_sentiment` | `review` | `user_generated` | 콘텐츠/OTT 사용자 반응 참고 |
| LG유플러스 뉴스룸 | `competitor_official` | `press_release` | `official` | 경쟁사(U+tv) 공식 발표 비교 |
| Netflix 미디어 센터 | `competitor_official` | `press_release` | `official` | 글로벌 OTT 대체재 공식 발표 |
| Disney+ 프레스룸 | `competitor_official` | `press_release` | `official` | 글로벌 OTT 대체재 공식 발표 |
| 방송미디어통신위원회 보도자료 | `regulatory_official` | `press_release` | `official` | 방송·통신 규제 정책 1차 출처 |
| 미디어통계포털 | `regulatory_official` | `press_release` | `official` | 국내 미디어·통신 시장 연구 보고서 |
| 네이버 뉴스 | `search` | - | `common` | 공통 Source, 일반 뉴스 보완 |

## Source 선정 이유

### SK브로드밴드 뉴스룸

- SK브로드밴드의 서비스, 기술, 제휴 관련 공식 1차 자료
- 신규 서비스, AI 적용 사례, 사업 방향 등 산업동향 분석에 활용
- 기업 공식 자료이므로 사실 확인의 기준점으로 사용

### SK텔레콤 IR 자료실 (SK브로드밴드 연결 실적)

- SK텔레콤 공식 IR 자료에서 연결 자회사인 SK브로드밴드의 유선·미디어 사업 실적과 주요 KPI를 확인하기 위한 1차 자료
- 매출·영업이익 등 IR/실적 관점 질문에 대응하는 `official` 역할 소스 (뉴스룸의 서비스 뉴스와는 다른 각도)

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
- 단순 극장 통계 기관이 아니다 — KOFIC은 2013년 SK브로드밴드를 포함한 주요 IPTV/플랫폼
  사업자(KT, LG유플러스, 홈초이스)와 데이터 연동 협약을 맺어, 온라인상영관 통합전산망(VKOBIS)을
  통해 SK브로드밴드(B tv) 등 IPTV 플랫폼의 디지털 영화 VOD 이용 건수·온라인 박스오피스 순위,
  극장·온라인(IPTV) 합산 관람 데이터까지 집계한다(2026-08-06 사용자 확인) — SK브로드밴드 IPTV VOD
  사업 자체와 직접 연결되는 자료다
- 웹 상세 페이지에서 PDF 다운로드 파라미터를 추출한 뒤 Firecrawl parse로 본문을 수집한다.

### 전자신문(통신)

- 통신·미디어 산업의 주요 뉴스와 해설 기사 보완
- 공식 발표만으로 부족한 시장 반응과 산업 맥락 확인에 활용
- 단, 일반 뉴스이므로 공식 Source와 Cross Check가 필요하다.

### 왓챠피디아

- OTT·콘텐츠 소비자의 반응과 관심도를 참고하기 위한 user sentiment Source
- 정량 신뢰도 판단보다는 보조적 사용자 반응 확인 목적으로 활용
- 사용자 리뷰 데이터는 대표성 한계가 있으므로 단독 근거로 사용하지 않는다.

### LG유플러스 뉴스룸 / Netflix 미디어 센터 / Disney+ 프레스룸

- IPTV(U+tv)뿐 아니라 글로벌 OTT 대체재(Netflix, Disney+)까지 경쟁 구도를 넓혀서 비교하기 위한 경쟁사 공식 자료
- 셋 다 자사 관점 발표라 `competitor_official` 역할로 등록, KT 뉴스룸과 함께 Cross Check 대상

### 방송미디어통신위원회 보도자료

- 망 사용료·개인정보·AI 콘텐츠 규제 등 정책 리스크를 확인하는 정부 공식 1차 출처
- 기존에 `regulatory_official` 역할이 비어있던 카테고리를 채움

### 미디어통계포털

- 국내 미디어·통신 시장에 대한 심도 있는 연구 보고서를 발행하는 공공 통계 포털
- 방송미디어통신위원회 보도자료와 함께 `regulatory_official` 역할 보강 목적으로 2026-08-03 사용자 검토를 거쳐 신규 등록
- 통계 포털 특성상 매일 갱신되지 않아 `frequency`는 `weekly`로 설정

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

## AI 게이팅 검색 (`collection_method: "ai_gated_search"`)

KOFIC처럼 고정된 게시판/PDF 다운로드가 필요하지는 않지만, 일반 role 기반 검색어
사다리(`build_source_search_terms`/`build_search_queries`)로는 그 사이트 특유의
용어를 못 맞추거나(예: 사용자 질문 문구와 그 사이트 자체 표현이 다름), 아무
질문에나 무조건 검색을 시도하는 게 낭비인 소스가 나오면 이 방식을 쓴다. KOFIC의
관련성 게이트/검색어 생성 로직(`_ai_source_gate_relevant`,
`_ai_generate_search_query`, `sectors/sk_broadband/adapter/collector/__init__.py`)
을 그대로 재사용하는 범용 버전이며, KOFIC의 게시판 목록 파싱이나 PDF 다운로드
같은 사이트 전용 코드는 전혀 없다 — 순수하게 "GPT가 쓸지 판단 → GPT가 검색어를
만듦 → Firecrawl이 도메인 제한 검색+스크랩"만 한다.

1. GPT가 질문이 이 소스의 등록된 `topics`와 관련 있는지 먼저 판단(무관하면 아예
   수집을 건너뜀)
2. GPT가 이 소스의 `topics`에 맞는 짧은 검색어 하나를 생성(사용자 질문 원문이
   아니라 그 사이트가 쓸 법한 표현으로)
3. Firecrawl이 그 검색어로 해당 소스 도메인에 한정해 검색 + 스크랩

**폴백 없음**: GPT 판단이 "무관"이거나, 검색어 생성이 실패/빈 값이거나, 검색
결과가 0건이면 그 소스는 그냥 0건으로 끝난다 — 기존 규칙 기반 사다리로 재시도하지
않는다(2026-08-06 사용자 결정, KOFIC 검색 경로에서 먼저 적용됨). 등록만 하면
`sources/registry/sk_broadband/sources.json`의 `collection_method`에
`"ai_gated_search"`를 추가하는 것으로 끝 — 새 소스 전용 코드는 필요 없다.

## 향후 검토 Source

방송통신위원회는 "방송미디어통신위원회 보도자료"로 이름을 갱신해 이번에 실제 등록했다(구 URL `kcc.go.kr`가 `kmcc.go.kr`로 리다이렉트됨 — 기관명 변경으로 추정).

정보통신정책연구원(KISDI)은 여전히 후보로 보존한다 — 정책·통신시장 분석에 의미가 있으나, 이번 검증에서 제안된 URL(`/report/reportList.do`, `/boardList.do?boardId=REPORT&pageId=www146`)이 모두 접속 실패(404)해서 등록하지 못했다. 정확한 보고서 목록 URL을 확인하면 추가한다.

### 이번에 반려된 후보 (2026-08-01 검증)

신규 후보 14개 중 아래 7개는 실제 접속 검증에서 탈락해 등록하지 않았다 — 다음에 이 소스들을 다시 검토할 때 참고할 것:

| 후보 | 문제 |
|---|---|
| SK텔레콤 뉴스룸(SKT Insight) | 리다이렉트 결과 SK텔레콤 자체 뉴스룸으로 연결됨 — SK브로드밴드 섹터와 무관, 등록 대상 아님 |
| CJ ENM 보도자료 (TVING) | 제안된 URL 404, 대체 경로도 실패 |
| 과학기술정보통신부 보도자료 | 제안된 URL들이 모두 "시스템 점검 중" 안내 페이지로 연결됨, 실제 게시판 아님 |
| 정보통신정책연구원(KISDI) 발간물 | 제안된 URL 404 (위 항목 참고) |
| 한국방송통신전파진흥원(KCA) 동향보고서 | 제안된 URL 404, 대체 경로 불명확 |
| 블로터 (미디어/OTT 섹션 의도) | 페이지는 로드되나 실제로는 "건설/부동산" 섹션 — 섹션 코드가 틀림 |
| 미디어오늘 (미디어 산업 섹션 의도) | 페이지는 로드되나 실제로는 "정치" 섹션 — 섹션 코드가 틀림 |

블로터·미디어오늘은 매체 자체는 유효하니, 올바른 섹션 코드만 다시 확인하면 등록 후보로 재검토 가능하다.

## 등록 원칙

- 실제 실행용 Source 정보는 같은 폴더의 `sources.json`에 등록한다.
- Source 수를 무작정 늘리지 않고, 공식성·시장분석·뉴스 보완·사용자 반응 역할이 겹치지 않게 관리한다.
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않는다.
- 새로운 Source를 추가할 때는 `role`, `content_type`, `collection_method`, `frequency`, `reliability_reason`을 함께 확인한다.
- 사용자 반응 Source는 보조 신호로만 사용하고, 공식·시장분석 Source와 Cross Check한다.
