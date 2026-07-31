# SK이노베이션 (SK Innovation) sector

Status: `template_only` profile로 유지 중. 다만 routing metadata, source registry, system prompt, collector/processor/validator/analyzer 구현 구조는 준비되어 있다. 실제 운영 전환 여부는 API Key, 비용, 품질 검증 후 결정한다.

SK이노베이션 섹터 - 배터리(SK온)·정유(SK에너지)·석유화학(SK지오센트릭)·
윤활유(SK엔무브) 등 에너지 밸류체인 전반과 SK이노베이션-SK E&S 합병 이후
친환경에너지 사업 동향 분석.

## 라우팅 (profile.json)
- aliases: SK이노베이션, SK Innovation, 에스케이이노베이션, SK온, SKOn,
  SK에너지, SK지오센트릭, SK엔무브
- keywords: 배터리, 이차전지, 정유, 정제마진, 석유화학, 친환경에너지, ESS 등
  (전체 목록은 `profile.json` 참고)

## 소스 레지스트리 (`sources/registry/sk_innovation/sources.json`)
전용 Source 4개 등록: SK이노베이션 공식 뉴스룸(SKinno News), 전기신문(배터리·ESS 섹션),
디일렉(배터리 섹션), 이투뉴스(산업 섹션). 공통 Source인 네이버 뉴스는 `sources/registry/common/`에서 자동 병합됩니다. 각 소스의
`collection_method`/`frequency`/`reliability_reason`/`reliability_tier`는
registry 파일에 명시되어 있으며, 등록되지 않은 소스에는 임의로 신뢰도를
부여하지 않습니다. 전기신문/디일렉/이투뉴스는 이번 구현 단계에서 실제 방문으로
재검증하여 루트 도메인에서 실제 서브섹션 URL로 갱신했습니다. SKinno News는
자동화된 방문 시 유효하지 않은 TLS 인증서가 확인되어 루트 도메인으로 유지했습니다
(실제 수집 시 인증서 오류 처리 여부 확인 필요).

## 분석 프롬프트 (`prompts/system_prompt.md`)
배터리·정유·석유화학·에너지 관점에서 포함/제외 범위, 핵심 키워드·용어집, 국내외
주요 경쟁사, 실제 질문 예시, 중요도 판단 기준, 다른 SK 계열사(하이닉스/텔레콤/
브로드밴드/플래닛)와 헷갈리기 쉬운 질문 구분표, 대상별(임원/실무진/외부인/경영진)
강조 포인트까지 정의되어 있습니다.

## 아직 안 된 것

- `profile.json.status`는 아직 `template_only`이다.
- 실제 운영 전환 전 `.env`에 `FIRECRAWL_API_KEY`와 `TRENDSPARC_SK_INNOVATION_ANALYZER_API_KEY`를 채워야 한다.
- sector reporter 단계는 공통 report planner와 역할을 분리해 추후 정리한다.
