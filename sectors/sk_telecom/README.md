# SK텔레콤 (SK Telecom) sector

Status: `template_only` profile로 유지 중. 다만 routing metadata, source registry, system prompt, collector/processor/validator/analyzer 구현 구조는 준비되어 있다. 실제 운영 전환 여부는 API Key, 비용, 품질 검증 후 결정한다.

SK텔레콤 섹터 - 5G/6G 이동통신 인프라, AI 서비스(에이닷/A.X), AI 데이터센터·
피지컬 AI(로봇/UAM), 알뜰폰·요금제 정책 및 텔코 LLM 얼라이언스 동향 분석.

## 라우팅 (profile.json)
- aliases: SK텔레콤, SKT, SK telecom, SK Telecom, 에스케이텔레콤, 011
- keywords: 5G/6G, 에이닷/A.X, AI 데이터센터, 피지컬 AI/로봇, UAM, 알뜰폰,
  요금제, T멤버십, T우주 등 (전체 목록은 `profile.json` 참고)

## 소스 레지스트리 (`sources/registry/sk_telecom/sources.json`)

현재 전용 Source 4개를 등록한다. 공통 Source인 네이버 뉴스는 `sources/registry/common/`에서 자동 병합된다.

- SK텔레콤 공식 뉴스룸 (보도자료)
- 전자신문 (IT·통신 섹션)
- 디지털데일리 (통신/미디어 섹션)
- 정보통신정책연구원(KISDI) 통신시장 경쟁상황 평가

각 소스의 `collection_method`, `frequency`, `role`, `content_type`, `reliability_reason`, `reliability_tier`는 registry 파일에 명시되어 있으며, 등록되지 않은 소스에는 임의로 신뢰도를 부여하지 않는다.
## 분석 프롬프트 (`prompts/system_prompt.md`)
이동통신·AI 서비스·인프라 관점에서 포함/제외 범위, 핵심 키워드·용어집, 국내외
주요 경쟁사, 실제 질문 예시, 중요도 판단 기준, 다른 SK 계열사(하이닉스/브로드밴드/
플래닛/이노베이션)와 헷갈리기 쉬운 질문 구분표, 대상별(임원/실무진/외부인/경영진)
강조 포인트까지 정의되어 있습니다.

## 아직 안 된 것

- `profile.json.status`는 아직 `template_only`이다.
- 실제 운영 전환 전 `.env`에 `FIRECRAWL_API_KEY`와 `TRENDSPARC_SK_TELECOM_ANALYZER_API_KEY`를 채워야 한다.
- sector reporter 단계는 공통 report planner와 역할을 분리해 추후 정리한다.
