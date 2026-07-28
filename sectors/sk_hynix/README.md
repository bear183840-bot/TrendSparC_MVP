# SK hynix sector

Status: `template_only` — routing metadata, source registry, and system
prompt are filled in, but `adapter/{collector,processor,validator,analyzer,
reporter}` are still stub functions. Every function under `adapter/` raises a
`PipelineStageError` explaining that it is not implemented yet. Do not add
fake/simulated data here — implement the adapter for real using the scope
and sources already defined below.

## 라우팅 (profile.json)
- aliases: SK hynix, SK하이닉스, 하이닉스, 에스케이하이닉스, 000660
- keywords: HBM/DRAM/NAND 등 기술, 투자/CAPEX, 실적, M&A, 공급망, 경쟁사(NVIDIA/TSMC/Micron/삼성전자), 정책/규제 등 (전체 목록은 `profile.json` 참고)

## 소스 레지스트리 (`sources/registry/sk_hynix/sources.json`)
5개 등록: SK하이닉스 뉴스룸, 삼성전자DS 뉴스룸, 전자신문(반도체), TrendForce Press Center(시장조사),
BIS 미국 상무부 산업안보국 Newsroom(수출통제 등 규제 공식 발표).
각 소스의 `collection_method`/`frequency`/`reliability_reason`은 registry 파일에 그대로 명시되어 있으며,
등록되지 않은 소스에는 임의로 신뢰도를 부여하지 않습니다.

## 분석 프롬프트 (`prompts/system_prompt.md`)
전략기획팀 실무자 관점의 8개 앵글(시장 동향/경쟁사 전략/재무·실적/투자/M&A·제휴/정책·규제/리스크/기회요인)
기준으로 문서를 분석하도록 정의되어 있음. 포함 범위는 DRAM/NAND/HBM 시장·투자·실적과 경쟁사 비교,
공급망 리스크까지이며, 파운드리 자체 공정기술 심층분석과 통신/네트워크(sk_broadband 담당)는 제외.

## 아직 안 된 것
`adapter/collector`부터 `adapter/analyzer`까지 — 위 레지스트리/프롬프트를 실제로 사용해 수집·분석하는
로직은 아직 구현되지 않았습니다 (Block 1: 섹터 adapter 구현 단계에서 진행).
