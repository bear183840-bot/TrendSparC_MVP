# SK텔레콤 (SK Telecom) sector

Status: `active` — routing metadata, source registry, system prompt, and a
real adapter (`collector`/`processor`/`validator`/`analyzer`) are all
implemented, following the exact same pattern as `sk_hynix`/`sk_planet`.

SK텔레콤 섹터 - 5G/6G 이동통신 인프라, AI 서비스(에이닷/A.X), AI 데이터센터·
피지컬 AI(로봇/UAM), 알뜰폰·요금제 정책 및 텔코 LLM 얼라이언스 동향 분석.

## 라우팅 (profile.json)
- aliases: SK텔레콤, SKT, SK telecom, SK Telecom, 에스케이텔레콤, 011
- keywords: 5G/6G, 에이닷/A.X, AI 데이터센터, 피지컬 AI/로봇, UAM, 알뜰폰,
  요금제, T멤버십, T우주 등 (전체 목록은 `profile.json` 참고)

## 소스 레지스트리 (`sources/registry/sk_telecom/sources.json`)
4개 등록: SK텔레콤 공식 뉴스룸(보도자료), 전자신문(IT·통신 섹션), 디지털데일리
(통신/미디어 섹션), 지디넷코리아(방송/통신 섹션). 각 소스의
`collection_method`/`frequency`/`reliability_reason`/`reliability_tier`는
registry 파일에 명시되어 있으며, 등록되지 않은 소스에는 임의로 신뢰도를
부여하지 않습니다. 지디넷코리아는 이번 구현 단계에서 실제 방문으로 재검증하여
루트 도메인에서 실제 방송/통신 섹션 URL로 갱신했습니다.

## 분석 프롬프트 (`prompts/system_prompt.md`)
이동통신·AI 서비스·인프라 관점에서 포함/제외 범위, 핵심 키워드·용어집, 국내외
주요 경쟁사, 실제 질문 예시, 중요도 판단 기준, 다른 SK 계열사(하이닉스/브로드밴드/
플래닛/이노베이션)와 헷갈리기 쉬운 질문 구분표, 대상별(임원/실무진/외부인/경영진)
강조 포인트까지 정의되어 있습니다.

## 아직 안 된 것
없음 — collector부터 analyzer까지 sk_hynix/sk_planet과 동일한 패턴으로
구현되어 있습니다. 실제 사용 전 `.env`에 `FIRECRAWL_API_KEY`와
`TRENDSPARC_SK_TELECOM_ANALYZER_API_KEY`를 채워야 합니다.
