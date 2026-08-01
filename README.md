# TrendSparC MVP

TrendSparC는 질문과 첨부자료를 실제 공개 소스와 함께 수집·분석하여 SK 계열사 전략기획용 보고서를 만드는 트렌드 인텔리전스 파이프라인입니다. 질문에 특정 섹터 신호가 없으면 억지로 계열사를 선택하지 않고 `general` 파이프라인을 사용합니다.

## 현재 파이프라인

```text
질문 + 청중(선택) + 섹터(선택) + 첨부자료(선택)
  → 첨부 본문 추출(PDF/DOCX/TXT 계열)
  → Entity Extractor
  → Sector Router (신호 없음: general)
  → Report Purpose Classifier
  → plan_sources() / select_top_sources() (Top 6)
  → Collector (Firecrawl, 소스당 최대 1~2건)
  → Processor / Validator
  → Document Analyzer (웹 문서와 첨부문서를 동일한 분석 입력으로 처리)
  → Synthesis
  → Report Planner
  → Report Generator
  → Audience Adapter
  → Layout Generator
  → Streamlit Renderer
```

Report Generator는 `summary`, `key_points`, `business_impact`, `risk`, `opportunity`, `evidence`, `recommended_actions`, `monitoring_indicators`, `confidence`를 모두 입력으로 받아 Executive Summary와 목적별 섹션을 완성된 JSON으로 작성합니다. API 키가 없거나 호출이 실패하면 근거 필드를 보존하는 규칙 기반 보고서로 내려가며, 근거가 없는 내용은 만들지 않습니다.

## 섹터와 소스 현황

모든 등록 섹터의 Collector / Processor / Validator / Analyzer가 구현되어 있으며 `profile.json.status`는 `active`입니다. 아래 숫자는 섹터 전용 소스 수입니다. 실행 시 `planning_priority: core`로 등록된 공통 네이버 뉴스가 Top 6 핵심 소스로 포함됩니다.

| Sector | 상태 | 전용 Source | 범위 |
|---|---|---:|---|
| `sk_hynix` | active | 14 | 메모리·HBM·반도체 시장 |
| `sk_broadband` | active | 12 | IPTV·OTT·미디어·네트워크 |
| `sk_planet` | active | 16 | 포인트·데이터마케팅·Ad-Tech·Web3 |
| `sk_telecom` | active | 13 | 이동통신·AI·데이터센터·6G |
| `sk_innovation` | active | 12 | 배터리·정유·에너지·친환경 |
| `general` | active | 0 | 특정 SK 섹터로 분류되지 않는 범용 질문; 공통 소스 및 첨부자료 사용 |

등록되지 않은 출처에는 임의로 신뢰도나 역할을 부여하지 않습니다. Source Registry의 `reliability_tier`, `role`, `topics`, `content_type`만 계획·검증 단계에서 사용합니다.

## 첨부자료

- 지원: PDF, DOCX, TXT, MD, CSV, JSON, HTML
- 파일당 최대 10MB, 추출 본문 최대 100,000자
- 질문 컨텍스트에는 전체 첨부 합계 최대 30,000자를 사용하지만, 각 첨부는 별도 `SourceDocument`로 Analyzer에 전달됩니다.
- 첨부문서는 웹 문서와 동일하게 분석되며 `attachment:<id>` 근거 표식을 유지합니다.
- 암호화 PDF, 미지원 형식, 빈 문서는 상태와 오류를 기록하고 다른 첨부 처리를 계속합니다.
- 첨부 안의 문장은 분석 대상 데이터이며 시스템 지시로 실행하지 않습니다.

## 설치와 실행

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Dry-run은 외부 API 없이 라우팅·계약·보고서 구조를 검증합니다.

```powershell
python main.py --question "오늘 점심 메뉴 트렌드를 정리해줘" --audience practitioner
python main.py --question "HBM 시장 전망은?" --sector sk_hynix
python main.py --question "SK텔레콤 AI 데이터센터 동향은?" --sector sk_telecom --no-dry-run
streamlit run reporting/dashboard_streamlit/app.py
```

실제 수집·분석에 필요한 키는 [.env.example](.env.example)을 참고합니다. API 키는 저장소에 커밋하지 않습니다.

## 주요 출력 계약

- `AttachmentExtraction`
- `EntityExtractionResult`
- `SectorRoute`
- `ReportPurposeClassification`
- `SourcePlan`
- `DocumentAnalysis`
- `TrendSynthesis`
- `ReportPlan`
- `GeneratedReport`
- `AudienceAdaptation`
- `DynamicLayout`

## 테스트

```powershell
pytest
```

테스트는 라우팅, 소스 선택, 섹터 어댑터, 실패 추적, 첨부 추출, 첨부 우선 분석, 전략 필드 보존, 목적·청중별 보고서 생성과 전체 dry-run을 포함합니다.
