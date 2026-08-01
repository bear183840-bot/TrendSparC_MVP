# TrendSparC_MVP

TrendSparC_MVP는 SK 계열사/사업영역별 질문을 받아 `intent`, `entity`, `sector`를 분석하고, 섹터별 Source를 계획한 뒤, 분석 결과를 대상 독자(audience)에 맞게 보고서 구조로 변환하는 AI Trend Intelligence 플랫폼 MVP입니다.

현재 저장소의 핵심 목적은 “한 번에 완성된 서비스”가 아니라, 여러 팀원이 각자 조사한 Source와 프롬프트를 같은 구조 안에 안전하게 넣을 수 있는 멀티 섹터 플랫폼 구조를 만드는 것입니다.

## 전체 처리 흐름

```text
사용자 입력
- 질문
- 청중(선택)
- 첨부자료·URL(선택)
        ↓
[1] Entity Extractor
- 기업, 기술, 핵심 키워드 추출
- 질문의 기본 intent 추정
- 규칙 기반 우선, 애매할 때 OpenAI
        ↓
[2] Sector Router
- SK하이닉스 / SK브로드밴드 / SK텔레콤 등 자동 분류
- API 사용 없음
        ↓
[3] Report Purpose Classifier
- 현황 파악
- 이슈 대응
- 미래사업
- 원인·문제 분석
- 규칙 기반 우선, 애매할 때 OpenAI
        ↓
[4] plan_sources()
- 해당 섹터에 등록된 전체 후보 소스 반환
- API 사용 없음
        ↓
[5] select_top_sources()
- 질문 키워드
- 기업·기술
- 보고 목적
- source topics / intents / role
를 기준으로 관련 소스 Top 6 선택
- API 사용 없음
        ↓
[6] Collector
- 선택된 6개 소스만 검색·수집
- Firecrawl API 사용
- 소스당 최대 1~2건
        ↓
[7] Processor
- 본문 정제
- 중복 제거
- 메타데이터 표준화
- API 사용 없음
        ↓
[8] Validator
- 관련성
- 최신성
- 출처 유무
- 최소 본문 길이
- 신뢰도 역할 검사
- API 없이 규칙 기반 우선
        ↓
[9] Document Analyzer
- global_system_prompt
+ sector별 system_prompt
를 사용해 문서 분석
- OpenAI API 사용

출력 예:
- summary
- key_points
- business_impact
- risk
- opportunity
- evidence
- recommended_actions
- confidence
        ↓
[10] Synthesis
- 여러 문서의 분석 결과 통합
- 중복 제거
- 출처 간 충돌 확인
- 핵심 근거 정렬
- OpenAI API 사용
        ↓
[11] Report Generator
- synthesis 결과
+ 보고 목적별 프롬프트
+ 청중별 프롬프트
를 한 번에 결합
- OpenAI API 사용

출력:
- 섹션별 서로 다른 내용
- Executive Summary
- Issue / Impact / Action 등
- 청중에 맞는 표현과 깊이
        ↓
[12] Layout Generator
- Report Generator의 구조화 JSON을
  카드, 표, 차트, 타임라인으로 배치
- API 사용 없음
        ↓
[13] Renderer
- Streamlit Dashboard
- 1-page PDF
- PPT 또는 HTML

## 현재 구현 범위

- `core/`의 계약 객체와 오케스트레이션 구조는 실제 구현되어 있고 테스트됩니다.
- `sectors/` 폴더를 스캔해 섹터를 동적으로 등록합니다.
- `sources/registry/<sector_id>/sources.json`과 `sources/registry/common/sources.json`을 읽어 SourcePlan을 만듭니다.
- 섹터별 README, `profile.json`, `system_prompt.md`, Source Registry를 기준으로 팀원들이 같은 방식으로 확장할 수 있습니다.
- 기본 실행은 `dry-run`이며, 실제 API 호출이 필요한 단계는 명시적으로 실행해야 합니다.
- `sk_broadband`와 `general`은 아직 Template Adapter 중심입니다.

## Sector 상태

`profile.json`의 `status`는 현재 운영 전환 전이라 대부분 `template_only`로 유지되어 있습니다. 다만 Source Registry와 일부 Adapter 구현은 섹터별로 준비 정도가 다릅니다.

| Sector | 현재 상태 | 등록 Source | 비고 |
|---|---|---:|---|
| `sk_hynix` | 구조/프롬프트/소스 등록 완료 | 전용 5개 + 공통 네이버 | collector/processor/validator/analyzer 구현 패턴 존재 |
| `sk_planet` | 구조/프롬프트/소스 등록 완료 | 전용 5개 + 공통 네이버 | 데이터·마케팅 플랫폼 관점 |
| `sk_telecom` | 구조/프롬프트/소스 등록 완료 | 전용 4개 + 공통 네이버 | KISDI를 market_analysis Source로 사용 |
| `sk_innovation` | 구조/프롬프트/소스 등록 완료 | 전용 4개 + 공통 네이버 | 배터리·정유·에너지 관점 |
| `sk_broadband` | Template 중심 | 전용 5개 + 공통 네이버 = 최대 6개 | 팀원 제공 Source 기준 유지, 실제 Adapter는 추후 구현 |
| `general` | fallback template | 공통 네이버 | 섹터 미지정 질문 fallback |

## Source 관리 원칙

- 섹터별 Source는 `sources/registry/<sector_id>/sources.json`에 등록합니다.
- 모든 섹터에 공통으로 들어갈 Source는 `sources/registry/common/sources.json`에 등록합니다.
- 현재 공통 Source는 네이버 뉴스이며, 섹터별 SourcePlan에 자동 병합됩니다.
- Source는 역할(role)을 가집니다.
  - `official`: 계열사 공식 자료
  - `search`: 일반 뉴스/검색성 자료
  - `market_analysis`: 시장·산업 분석 자료
  - `competitor_official`: 경쟁사 공식 자료
  - `regulatory_official`: 규제/정부 공식 자료
  - `user_sentiment`: 사용자 반응/리뷰성 자료
- 등록되지 않은 Source에는 임의로 신뢰도나 역할을 부여하지 않습니다.

## 설치 방법

```bash
cd TrendSparC_MVP
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Dry-run Pipeline 실행

```bash
python main.py --question "SK하이닉스 HBM 시장 전망은?" --audience practitioner
python main.py --request-file examples/requests/sample_request.json
python main.py --question "..." --sector sk_totally_made_up
python main.py --question "..." --force-fail-stage intent
```

실행 결과에는 `StageTrace`와 중간 계약 객체가 JSON 형태로 출력됩니다.

주요 중간 객체:

- `IntentResult`
- `EntityExtractionResult`
- `SectorRoute`
- `SourcePlan`
- `TrendSynthesis`
- `ReportPlan`
- `AudienceAdaptation`
- `DynamicLayout`

## 실제 Adapter 실행

기본은 비용과 실패 추적을 위해 `dry-run`입니다. 실제 수집·분석을 시도하려면 API Key를 `.env`에 넣고 `--no-dry-run` 옵션을 사용합니다.

```bash
python main.py --question "SK텔레콤 AI 데이터센터 동향은?" --sector sk_telecom --no-dry-run
```

필요한 환경변수 예시는 `.env.example`을 참고합니다. 실제 API Key는 GitHub에 올리지 않습니다.

## Streamlit UI 실행

```bash
streamlit run reporting/dashboard_streamlit/app.py
```

현재 UI는 질문 입력, 첨부, audience/sector 선택, Pipeline 결과 확인을 위한 구조 중심 화면입니다.

## 테스트

```bash
pytest
```

테스트 범위:

- 전체 dry-run trace
- unsupported sector routing
- 동적 sector registry
- forced failure trace
- entity / source planner / role 기반 source planning

## 아직 남은 작업

- `profile.json.status`를 실제 운영 단계에 맞게 `active`로 전환할지 결정
- `sk_broadband` 실제 Collector/Processor/Validator/Analyzer 구현
- sector reporter 단계 정리 또는 공통 reporter와 역할 분리
- 실제 Dashboard/HTML/PDF 렌더링 고도화
- Scheduler / n8n / 배포 방식 결정
- 팀원들이 조사한 추가 Source를 role/content_type 기준으로 정리해 registry에 반영

## 팀원 작업 시 주의사항

- 기존 섹터 구조를 복사하되, Source와 프롬프트 내용은 해당 섹터에 맞게 작성합니다.
- Source를 추가할 때는 README만 수정하지 말고 반드시 `sources.json`에도 반영합니다.
- 프롬프트는 `sectors/<sector_id>/prompts/system_prompt.md`에 관리합니다.
- API Key는 `.env`에만 넣고 코드나 README에 직접 쓰지 않습니다.
- 새로운 기능을 붙이기 전, 입력/출력 계약(JSON 구조)을 먼저 정합니다.
