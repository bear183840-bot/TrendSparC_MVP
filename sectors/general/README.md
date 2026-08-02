# General sector

Status: `active` — routing metadata, source registry, system prompt, and a
real adapter are all implemented.

`general`은 사용자의 질문에서 특정 SK 계열사나 사업 섹터가 명확히 잡히지 않지만,
그래도 조사·분석이 가능한 질문(계열사와 무관한 사회/경제/기술/문화/생활 주제 등)을
받는 리서치 섹터입니다. 순수 잡담/인사는 이 섹터로도 안 오고
`core/request_pipeline/direct_response.py` / entity 단계의 `response_mode`
분류에서 짧은 대화형 응답으로 먼저 걸러집니다.

## 라우팅 (profile.json)
- aliases: 없음 (다른 계열사에 매칭되지 않을 때의 fallback이므로 별도 별칭 불필요)
- keywords: 뉴스, 경제, 사회, 기술, 정책, 문화, 생활, 건강
- market_keywords: 최신 동향, 공식 발표, 전문가 분석
- key_metrics는 의도적으로 비워둠 — 계열사 무관 주제는 고정된 KPI 세트가 성립하지 않으므로, 가짜 지표를 만들지 않음.

## 소스 레지스트리 (`sources/registry/general/sources.json`)
전용 Source 3개 등록: 대한민국 정책브리핑(정부 공식 정책뉴스, role: regulatory_official),
경향신문(종합 일간지 최신기사, role: search), 통계청 KOSIS(국가통계포털, role:
market_analysis). 공통 Source인 네이버 뉴스는 `sources/registry/common/`에서
자동 병합됩니다(role: search). 각 소스의 URL은 실제 방문으로 검증했습니다 —
연합뉴스/한겨레/조선일보 등 일부 매체는 자동화된 방문이 차단되어 등록하지
않았습니다(추측으로 채우지 않음).

## 분석 프롬프트 (`prompts/system_prompt.md`)
특정 섹터 해석을 강제하지 않고, 질문의 실제 주제(사회/경제/기술/정책/문화/생활 또는
첨부 문서)를 그대로 분석하도록 안내합니다. 근거 문서에 없는 내용은 채우지
않고, 근거가 불충분하면 그렇다고 명시하도록 요구합니다.

## 어댑터 (adapter/)
- `collector`/`processor`/`validator`는 `sectors/sk_telecom/adapter/*`의 구현을
  그대로 재사용합니다 — 두 로직이 완전히 범용적(Firecrawl 검색 기반, 섹터명에
  의존하지 않음)이라 중복 구현하지 않고 import로 연결했습니다.
- `analyzer`는 general 전용으로 실제 구현되어 있으며, `business_impact`/`risk`/
  `opportunity`/`recommended_actions`/`monitoring_indicators`/`action_level`
  등 전략 판단에 쓰는 필드를 포함한 구조화된 스키마로 분석합니다.
- 실행 전 `.env`에 `FIRECRAWL_API_KEY`와 `TRENDSPARC_GENERAL_ANALYZER_API_KEY`가
  필요합니다.

## 아직 안 된 것
없음 — 위 구성 요소가 모두 실제로 연결되어 있습니다. 다만 리서치 결과 품질(특히
차트/시계열 데이터 구조화)은 다른 섹터와 마찬가지로 계속 개선 대상입니다.
