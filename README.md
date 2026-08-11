# TrendSparC MVP

TrendSparC는 질문 하나와 청중·보고 목적·SK 계열사를 해석하고, 실제 수집 근거만으로
전략기획 실무에 바로 사용할 수 있는 보고서와 동적 대시보드를 만드는 파이프라인입니다.
현재 최우선 섹터는 `sk_broadband`이며, 특정 섹터 신호가 없으면 `general`로
라우팅합니다. 속도보다 정확성·근거 추적·시각적 완성도를 우선합니다.

## 현재 파이프라인

```text
질문 + 청중 + 섹터(선택) + 첨부자료(선택)
  → 첨부 본문 추출
  → Entity Extractor / 질문 요구사항 구조화
  → Sector Router
  → Report Purpose Classifier
  → Block Priority Planner (수집 힌트)
  → Source Planner / Collector / Processor / Validator
  → Document Analyzer
    ↳ 검증 문서 부족 시 bounded 재수집
    ↳ 필수 요구사항·블록 데이터 부족 시 bounded 보강 수집
  → Synthesis (근거·수치·비교·원인·행동 구조화)
  → Report Planner / Report Generator
  → Audience Adapter / Layout Generator
  → Streamlit Dashboard
```

목적은 다음 네 가지입니다.

| purpose_id | 의미 |
|---|---|
| `current_status` | 현황 파악 |
| `root_cause` | 원인 분석 |
| `issue_response` | 이슈 대응 |
| `future_business` | 미래사업·전략 |

복합 질문은 `secondary_purpose_id`와 명시적 요구사항(비교·추이·추천·원인·대응 등)을
함께 보존합니다. `추천`이라는 단어 하나만으로 미래사업으로 보내지 않도록 질문의
시간축과 실제 산출물을 같이 판정합니다.

## 동적 대시보드 구조

목적별 읽기 흐름은 `common/purpose_slots.py`가 정의합니다. 슬롯마다 후보 블록을
우선순위대로 검사하되, 최종 선택은 `common/block_shapes.py`의 결정론적 데이터 계약을
통과한 블록만 가능합니다.

- 1패스에서 각 슬롯의 대표 블록을 먼저 정합니다.
- 2패스에서 아직 표현되지 않은 근거를 가진 companion 블록만 추가합니다.
- `core/block_priority_planner/`는 수집 전에 필요한 데이터 모양을 알려주는 힌트이며,
  렌더링을 강제하지 않습니다.
- 실제 Streamlit 슬롯 렌더러는
  `reporting/dashboard_streamlit/blocks/slot_blocks.py`의 레지스트리를 사용합니다.
- 근거가 부족하면 숫자·등급·원인 관계를 만들어 채우지 않습니다.

현재 블록은 KPI, 라인/영역, 막대·순위, 그룹 막대, 구성비, 타임라인, 비교·벤치마크
테이블, SWOT/의사결정 매트릭스, 원인맵·원인트리, 요인 영향도, 액션 리스트,
키워드/반복 언급, 출처 패널 등을 포함합니다. 같은 디자인 체계 안에서 질문과 데이터
모양에 따라 조합이 달라집니다.

## 근거와 구조화 원칙

- 모든 수치와 주장은 수집 문서의 문장·문서 ID·출처로 추적할 수 있어야 합니다.
- 표에 여러 시점·연령·기업·플랫폼이 있으면 대표값 하나로 줄이지 않고 각각 보존합니다.
- YoY·CAGR·증감률·배수는 원문에 직접 나온 상대지표로만 저장하며, 보이지 않는
  기준값이나 절대값을 역산하지 않습니다.
- 회사/플랫폼과 지표 이름은 명시적으로 검토된 bilingual alias만 합칩니다. 문자열이
  비슷하다는 이유로 엔터티나 서로 다른 측정값을 합치지 않습니다.
- 비교 블록은 공통 기준이 있는 대상끼리만, 원인 블록은 검증된 인과 연결이 있을 때만
  사용합니다.
- AI 호출 실패 시 규칙 기반 경로로 폴백하며 파이프라인 전체를 중단하지 않습니다.

## 섹터와 소스 현황

모든 등록 섹터의 Collector / Processor / Validator / Analyzer가 구현되어 있고
`profile.json.status`는 `active`입니다. 아래 숫자는 각 `sources.json`의 섹터 전용
소스 수이며, 공통 소스는 별도로 병합됩니다.

| Sector | 전용 Source | 범위 |
|---|---:|---|
| `sk_broadband` | 12 | IPTV·OTT·미디어·초고속인터넷·네트워크 |
| `sk_hynix` | 14 | 메모리·HBM·반도체 시장 |
| `sk_planet` | 16 | 포인트·데이터마케팅·Ad-Tech·Web3 |
| `sk_telecom` | 13 | 이동통신·AI·데이터센터·6G |
| `sk_innovation` | 12 | 배터리·정유·에너지·친환경 |
| `general` | 3 | 특정 SK 섹터로 분류되지 않는 범용 조사 |

실제 등록 URL과 역할은 `sources/registry/<sector>/sources.json`이 단일 기준입니다.
등록되지 않은 출처에는 임의로 신뢰도나 역할을 부여하지 않습니다.

## 설치와 실행

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Dry-run은 외부 API 없이 라우팅·계약·계획 구조를 검증합니다.

```powershell
python main.py --question "국내 IPTV 시장은 어떻게 변하고 있나?" --sector sk_broadband
python main.py --request-file examples/requests/sample_request.json
```

실제 실행 결과를 저장하면 같은 결과를 대시보드에서 다시 열 수 있습니다.

```powershell
python main.py --question "OTT 이용 추이를 비교해줘" --sector sk_broadband --no-dry-run --save-result runs/ott.json
python main.py --resume-from runs/ott.json --save-result runs/ott_v2.json
streamlit run reporting/dashboard_streamlit/app.py --server.port 8503
```

- `--resume-from`은 저장된 문서를 재사용해 검색·스크레이핑을 건너뜁니다.
- `--synthesis-fixture tests/fixtures/synthesis_brand_marketing.json`은 수집부터 synthesis까지
  건너뛰고 리포트·슬롯·렌더링을 무료로 검증합니다.
- `--summary-only`는 전체 JSON 대신 실행 요약을 출력합니다.
- API와 모델 설정은 [.env.example](.env.example)을 참고합니다. 실제 `.env`와 키는
  저장소에 커밋하지 않습니다.

## 첨부자료

- 지원: PDF, DOCX, TXT, MD, CSV, JSON, HTML
- 파일당 최대 10MB, 추출 본문 최대 100,000자
- 첨부는 별도 `SourceDocument`로 Analyzer에 전달되고 `attachment:<id>` 근거를 유지합니다.
- 암호화 PDF, 미지원 형식, 빈 문서는 오류를 기록하고 다른 문서 처리를 계속합니다.
- 첨부 내용은 분석 데이터이며 시스템 지시로 실행하지 않습니다.

## 테스트

```powershell
python -m pytest -q
```

현재 기준은 **1412 passed, 2 skipped**입니다(2026-08-11). 라우팅, 소스 계획,
어댑터, 근거 검증, 수치·비교 구조화, 목적별 슬롯, 블록 적격성, Streamlit 렌더링,
payload 예산과 전체 dry-run을 포함합니다.

에이전트가 작업을 이어받을 때는 [AGENTS.md](AGENTS.md)와 `CLAUDE.md`를 먼저 읽어야
합니다.
