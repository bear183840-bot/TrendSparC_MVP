# SK플래닛 (SK Planet) sector

Status: `template_only` — routing metadata, source registry, and system
prompt are filled in, but `adapter/{collector,processor,validator,analyzer,
reporter}` are still stub functions. Every function under `adapter/` raises a
`PipelineStageError` explaining that it is not implemented yet. Do not add
fake/simulated data here — implement the adapter for real using the scope
and sources already defined below.

SK플래닛 섹터 - OK캐쉬백, Syrup 중심의 포인트/마케팅 플랫폼, Target Intelligence
기반 AI/빅데이터 솔루션, Web3/블록체인 로열티 생태계 및 모바일 커머스/Ad-Tech
동향 분석.

## 라우팅 (profile.json)
- aliases: SK Planet, SK플래닛, 에스케이플래닛, Planet, 플래닛, OK캐쉬백, Syrup, 시럽
- keywords: OK캐쉬백/Syrup/시럽, Target Intelligence, 데이터 마케팅, 포인트·리워드,
  Web3/NFT/블록체인, CDP, Ad-Tech, 모바일 커머스, O2O, 마이데이터 등 (전체 목록은
  `profile.json` 참고)

## 소스 레지스트리 (`sources/registry/sk_planet/sources.json`)
5개 등록: SK플래닛 공식 뉴스룸, 전자신문(IT/데이터/플랫폼), 블로터(Web3/테크),
모바일인덱스(아이지에이웍스, 앱/트래픽 분석), 데이터넷(빅데이터/마케팅).
각 소스의 `collection_method`/`frequency`/`reliability_reason`은 registry 파일에
그대로 명시되어 있으며, 등록되지 않은 소스에는 임의로 신뢰도를 부여하지 않습니다.

## 분석 프롬프트 (`prompts/system_prompt.md`)
데이터 플랫폼·커머스·디지털 마케팅 관점에서 포함/제외 범위, 핵심 키워드·용어집,
국내외 주요 경쟁사, 실제 질문 예시, 중요도 판단 기준, 다른 섹터(반도체/미디어)와
헷갈리기 쉬운 질문 구분표, 대상별(임원/실무진/외부인/경영진) 강조 포인트까지
정의되어 있음.

## 아직 안 된 것
`adapter/collector`부터 `adapter/analyzer`까지 — 위 레지스트리/프롬프트를 실제로
사용해 수집·분석하는 로직은 아직 구현되지 않았습니다.
