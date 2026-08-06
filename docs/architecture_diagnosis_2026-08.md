# TrendSparC 구조 진단 리포트 (2026-08)

> 목적: "질문 성격과 무관하게 SWOT/Current Snapshot이 반복되고 시각화가 안 된다"는 증상의 구조적 원인을 개별 버그가 아닌 아키텍처 수준에서 규명한다. **이 문서는 진단만 다루며 코드 수정은 포함하지 않는다.**

## 요약 (먼저 읽을 것)

증상의 원인은 하나가 아니라 **서로 독립적인 4개의 단절**이며, 모두 동일한 형태다 — **상류 단계는 필요한 데이터를 만들어내는데, 하류 단계가 그것을 읽지 않는다.**

| # | 단절 지점 | 성격 |
|---|---|---|
| 1 | 청중의 고정 `report_structure`가 보고목적을 **완전히 덮어씀** | 로직 결함 (planner) |
| 2 | 대시보드 뷰가 `report_plan.sections`를 **아예 읽지 않음** | 로직 결함 (view) |
| 3 | 수치가 evidence 산문에만 있고 `metric_points`로 **추출되지 않음** | 추출 로직 부족 |
| 4 | `chart` 블록이 요구하는 `block.data.rows`를 **아무도 채우지 않음** | 배선 누락 |

**가장 중요한 결론: 정민님의 블록 라이브러리는 지금 병목이 아니다.** 새 시각 컴포넌트를 받아도 그것을 채울 데이터가 도달하지 않으므로, 지금 상태로는 라이브러리를 붙여도 같은 폴백이 반복된다. (근거: [질문 2])

---

## 진단의 한계 (먼저 밝힘)

`storage/requests/` 디렉터리가 **비어 있어** 과거 실행 기록이 디스크에 남아 있지 않다. 따라서 "질문 N개 중 몇 %" 같은 통계는 **채팅으로 공유된 실제 실행 결과 4건**에서만 집계했으며, 통계적 표본이 아니라 사례 기반이다.

- 이 문서의 **코드 경로·스키마·분기 조건**은 전부 저장소에서 직접 확인한 사실이다.
- 이 문서의 **건수 집계**는 표본 4건 기준이며, 그 한계를 각 항목에 명시했다.

> **우선 조치 제안**: PR #20이 추가한 `main.py --save-source-documents`와 `PipelineResult.collected_source_documents`를 활용해 실행 결과를 `storage/requests/`에 남기면, 다음 진단부터는 실제 통계를 낼 수 있다.

---

## [질문 1] 시각화를 만들 만큼 데이터가 충분한가?

### 확인한 근거

표본 4건(채팅으로 공유된 실제 실행):

| # | 질문 | 결과 | 구조화 수치 | 산문 속 수치 |
|---|---|---|---|---|
| A | IPTV/OTT 경쟁 심화가 B tv 전략에 미치는 영향 | **collector 중단** (documents=0) | — | — |
| B | IPTV/OTT 경쟁 (재시도) | **collector 중단** (documents=2, 독립출처 1) | — | — |
| C | 우리회사 매출 추이 + 전망 | 리포트 생성 성공 | **1건** | **3건** |
| D | Btv 가입자 수 변화 (req_cli_3093052e) | 리포트 생성 성공 | 3건(가입자수/시청률/채널순위) + 비교 2건 | 미상 |

**사례 C를 실제 추출기에 통과시켜 검증한 결과** (`common/content_quality_validator.py`):

```
'2024년 3분기 누적 매출액 3조 2,878억원'   → MISS  (추출 실패)
'2025년 매출액 4조 5,406억원'             → MISS  (추출 실패)
'2025년 영업이익 3,741억원 (전년 대비 6.2%)' → MISS  (추출 실패)
```
→ 이 3건은 **명백한 수치+시점 데이터인데 `metric_points`에 하나도 들어가지 않았고**, 실제로 화면에 남은 구조화 수치는 `특수관계자 매출액 비중 15.9% (2025년 1분기말)` **단 1건**이었다.

원인은 정규식이 연도와 라벨 사이의 회계 수식어(`누적`)를 허용하지 않았고, 라벨 자체도 좁게 잡혀 있었기 때문. (이 부분은 진단 중 이미 수정했고, 수정 후 3/3 추출 확인)

### 결론

**두 가지 실패가 모두 존재하며, 성격이 다르다.**

| 구분 | 건수 (표본 4건) | 내용 |
|---|---|---|
| **데이터 자체 부재** | **2건 (A, B)** | Firecrawl이 skbroadband.com에 도달 실패, 독립 출처 부족으로 collector 단계에서 중단. 시각화 이전에 리포트 자체가 없음 |
| **구조화 추출 실패** | **1건 (C)** — 해당 질문의 수치 4개 중 **3개(75%)** | 데이터는 수집됐고 evidence에 문장으로 존재하나 `metric_points`로 변환되지 않음 |
| 정상 | 1건 (D) | 구조화 수치 3건 + 비교 2건 확보 |

**핵심**: 사례 C는 "매출 추이"를 물었고 evidence에 2024·2025 두 시점의 매출이 실제로 있었다. 즉 **라인/바 차트를 그릴 데이터가 수집돼 있었는데 추출 단계에서 전부 흘렸다.** 이것이 "데이터가 없어서 시각화를 못 한다"는 인상을 만든 주된 원인이다.

### 다음에 고칠 것 (우선순위)

1. **(높음)** 수치 추출기 확장 — 회계 수식어(누적/연결/별도), 다양한 라벨(가입자·점유율·ARPU 등), YoY 증감 패턴. *(진단 중 1차 수정 완료, 라벨 확장은 미완)*
2. **(높음)** 수집 실패 자체 — 사례 A·B는 시각화 문제가 아니라 수집 문제. 별도 트랙으로 관리 필요
3. **(중간)** 실행 결과 영속화로 이 집계를 자동화

---

## [질문 2] 정확히 무엇이 필요한가? (3단계 진단)

### 확인한 근거 — 블록 레지스트리 실태

`reporting/dashboard_streamlit/blocks/`에 **11개 블록 + 4개 폴백**이 등록돼 있다. 각 블록이 요구하는 스키마를 전수 조사한 결과:

| 블록 | 요구 스키마 | 구조화 데이터 수용? |
|---|---|---|
| `chart` (line_area) | `opportunities/key_points/monitoring_indicators` = **전부 list[str]**<br>차트는 `block.data["rows"]` + `block.config["x"/"y"]` 필요 | ❌ |
| `metrics` (kpi_card) | `key_points/business_impacts/risks/opportunities` = list[str] | ❌ |
| `bar` | `key_points/opportunities/business_impacts` = list[str] | ❌ |
| `timeline` | `monitoring_indicators/opportunities/key_points` = list[str] | ❌ |
| `matrix` (SWOT) | `risks/opportunities` = list[str] | ❌ |
| `graph` (cause_map) | `summary/risks/key_points/evidence/actions` = list[str] | ❌ |
| `evidence` | `evidence` = list[str] | ❌ |
| `list` (action_list) | `actions/monitoring_indicators/key_points` = list[str] | ❌ |
| `table` | 필드 정의 없음 (extra="allow") | — |
| `radar` | `entity/criterion/value` | ✅ (유일) |

**즉 레지스트리 전체가 `list[str]` 텍스트 기반이며, `MetricPoint`/`ComparisonPoint` 같은 구조화 계약을 받는 블록은 `radar` 하나뿐이다.**

**결정적 사실**: `chart` 블록은 차트를 그릴 능력이 코드에 있으나(`st.area_chart`), 그것은 `block.data["rows"]`가 있을 때만이다. 저장소 전체를 검색한 결과 **`DashboardBlock`의 `data`/`config` 필드를 채우는 코드가 파이프라인 어디에도 없다** (`core/layout_generator/generator.py`는 `content=`만 전달). 따라서 `chart` 블록은 **구조적으로 항상 텍스트 폴백**만 출력한다:

```
"수치·시계열 근거가 없어 차트 대신 확인된 신호를 표시합니다."
```

**추가 사실**: 이 레지스트리는 **라이브 화면에서 도달 불가**다. `app.py`는 `renderer.py`를 import하지 않으며, 실제 화면은 `components.py`(구조화 데이터를 제대로 다룸 — `render_metric_chart`/`render_kpi_row`/`render_metric_bar`가 `MetricPoint`를 직접 사용)가 그린다. 즉 **렌더링 시스템이 두 벌 존재하고, 성능이 좋은 쪽(components.py)이 라이브, 텍스트 기반인 쪽(blocks/)이 사문화**돼 있다.

`blocks/purpose_templates.py` 역시 자체 docstring이 *"Nothing in the pipeline reads this yet"*이라고 인정하며, 참조하는 곳은 테스트 1개뿐이다.

### 3단계 진단 결과

| 사례 | ① 블록 스키마 없음? | ② Analyzer가 변환 안 함? | ③ layout_generator가 선택 안 함? |
|---|---|---|---|
| 매출 시계열 (사례 C) | — | **여기서 끊김.** 수치가 evidence 문자열로만 존재 | (선택 로직은 정상 — 데이터가 없어 chart 자격 미달 판정) |
| 원인 트리 | **여기서 끊김.** claim 간 부모-자식 필드가 계약에 없음 | 관계를 추출하지 않음 | — |
| 과거 vs 현재 | **여기서 끊김.** `ComparisonPoint`는 주체 간 비교 전용, 시점 축 없음 | — | — |
| 차트 일반 | `chart` 블록 존재하나 `data.rows`를 받는 배선 없음 | — | **여기서도 끊김** (data/config 미전달) |

### 결론

**"블록 라이브러리 부족"이 현재의 주 원인이 아니다.** 근거:

1. 시각화가 안 되는 1순위 원인은 **추출 실패**(사례 C: 수치 4개 중 3개 유실)이지 그릴 컴포넌트가 없어서가 아니다.
2. 이미 등록된 `chart` 블록조차 **데이터 배선이 없어** 못 쓰고 있다. 컴포넌트를 더 받아도 같은 벽에 부딪힌다.
3. 라이브 경로(`components.py`)에는 이미 라인차트·바·KPI·비교테이블·SWOT이 **구조화 데이터 기반으로 구현돼 있다.**

**단, 라이브러리가 불필요하다는 뜻은 아니다.** 다음 두 가지는 현재 코드로 커버 불가이며 새 컴포넌트가 실제로 필요하다:
- 원인 트리(Root Cause tree) — 계약·컴포넌트 **둘 다** 없음
- 과거 vs 현재 타임라인 — 계약·컴포넌트 **둘 다** 없음

→ **권고: 라이브러리 도입 전에 데이터 파이프라인(추출 + 배선)을 먼저 고친다.** 순서를 반대로 하면 라이브러리가 빈 껍데기로 붙는다.

### 다음에 고칠 것 (우선순위)

1. **(최상)** `blocks/` 레지스트리 스키마를 구조화 계약(`MetricPoint`/`ComparisonPoint`) 수용하도록 전환하거나, **레지스트리 경로를 폐기하고 `components.py`로 일원화** — 두 벌 유지는 그 자체가 비용
2. **(높음)** `layout_generator`가 `block.data`/`config`를 채우도록 배선 (또는 1번으로 해소)
3. **(중간)** 원인 트리 / 과거vs현재 — 계약 확장이 선행되어야 하므로 라이브러리 도착 시점과 맞춰 진행

---

## [질문 3] 항상 같은 블록이 박히는 정확한 원인

### 확인한 근거

**(a) 분류는 정상 작동한다.** "우리회사 매출 추이 알려주고 앞으로 전망 알려줘"를 실제 분류기에 통과시킨 결과:

```
purpose_id = current_status   confidence = high   secondary = None
```
질문 성격에 맞는 분류다. **분류기 결함이 아니다.**

**(b) 그런데 planner가 보고목적을 통째로 무시한다.** 4개 목적 × 2개 청중으로 `plan_report()`를 실제 실행한 결과:

```
current_status   practitioner -> ['overview','key_metrics','timeline','response_actions','risk','sources','market_status']
issue_response   practitioner -> ['overview','key_metrics','timeline','response_actions','risk','sources','market_status']
root_cause       practitioner -> ['overview','key_metrics','timeline','response_actions','risk','sources','market_status']
future_business  practitioner -> ['overview','key_metrics','timeline','response_actions','risk','sources','market_status']
```

**4개 목적이 전부 동일한 섹션 목록을 만든다.** 원인은 `core/report_planner/planner.py`:

```python
if profile.report_structure:
    sections = _dedupe_semantic_sections(list(profile.report_structure))   # ← 목적 무시
else:
    sections = _dedupe_semantic_sections(_BASE_SECTIONS + list(purpose_sections) + list(profile.focus))
```

그리고 청중 프로필을 전수 확인한 결과:

| 청중 | 고정 report_structure |
|---|---|
| practitioner | ✅ 있음 |
| executive | ✅ 있음 |
| management | ✅ 있음 |
| external | ✅ 있음 |
| `_default` | ❌ 없음 (UI에 노출 안 됨) |

**사용자가 선택할 수 있는 4개 청중이 전부 고정 구조를 갖고 있다.** 즉 실사용 경로에서는 **보고목적이 섹션 구성에 기여하는 바가 사실상 없다.** 목적별 차이는 `_content_backed_sections()`가 데이터 유무로 뒤에 덧붙이는 것뿐이다.

참고로 `_default`(고정 구조 없음)는 정상적으로 적응한다:
```
WITH metrics -> ['overview','key_metrics','market_status','timeline','sources']
NO metrics   -> ['overview','sources']    omitted={'recommended_action': '검증된 행동 근거가 없음'}
```
→ **적응 로직 자체는 잘 만들어져 있는데, 실사용 경로에서 도달하지 않는다.**

**(c) 화면은 섹션을 아예 읽지 않는다.** `reporting/` 전체에서 `report_plan`을 참조하는 곳은 2군데뿐이고, 둘 다 섹션과 무관하다(`app.py`는 `audience_id`만, `components.py`는 `GeneratedReport.sections`를 필드 병합용으로만). 대신 `generic_dashboard._panel_definitions(purpose_id)`가 목적별로 3패널을 하드코딩한다:

```python
if purpose_id == "future_business":  → Trend Drivers / Opportunity Map / Investment Signals
if purpose_id == "root_cause":       → Problem Definition / Cause Map / Improvement Plan
return                               → Current Snapshot / Market Signals / Near-term Outlook   # ← 그 외 전부
```

### 폴백 발동률

`generic_dashboard`에 도달하는 목적 기준:

| purpose | 전용 레시피 | 결과 |
|---|---|---|
| `issue_response` | — | 별도 뷰(`issue_response_view`)로 분기 |
| `future_business` | ✅ | 전용 3패널 |
| `root_cause` | ✅ | 전용 3패널 |
| **`current_status`** | ❌ | **폴백 (Current Snapshot/Market Signals/Near-term Outlook)** |

`generic_dashboard`가 처리하는 3개 목적 중 **1개(current_status)에 전용 레시피가 없다.** 그리고 `current_status`는 분류기 구조상 가장 흔한 분류다 — `classify_report_purpose()`의 폴백 기본값이자(`top_score == 0`일 때) "현황/추이/시장/실적" 등 광범위한 키워드가 매핑된다. 표본 4건 중 리포트가 생성된 2건(C, D)은 **둘 다 current_status → 폴백**이었다.

### 결론

**원인은 3중이며, 어느 하나만 고쳐도 증상이 사라지지 않는다.**

1. **planner**: 청중 고정 구조가 목적을 덮어씀 → 실사용 4개 청중 전부에서 목적이 무력화
2. **view**: `report_plan.sections`를 읽지 않음 → planner가 무엇을 정하든 화면에 반영 안 됨
3. **view**: `current_status` 전용 레시피 부재 → 가장 흔한 분류가 폴백으로 수렴

SWOT이 항상 보이는 것도 같은 뿌리다 — `generic_dashboard`는 `swot_field_count >= 2`면 무조건 SWOT 카드를 그리며, 이 판단에 질문 성격이나 목적이 개입하지 않는다.

### 다음에 고칠 것 (우선순위)

1. **(최상)** planner의 청중-목적 관계 재정의 — 고정 구조를 "목적이 정한 섹션을 청중에 맞게 **조정**"하는 방식으로 바꿀지, 아니면 목적을 우선하고 청중은 서술 톤·상세도만 담당할지 **정책 결정 필요** (설계 의사결정이므로 구현 전 합의 권장)
2. **(최상)** 뷰가 `report_plan.sections`를 따르도록 전환 — 2번을 고치지 않으면 1번을 고쳐도 화면은 그대로다
3. **(높음)** `current_status` 전용 레시피 추가 (KPI + 시계열 우선)

---

## [질문 4] "팀장 AI" 오케스트레이션이 필요한가?

### 확인한 근거

`core/request_pipeline/pipeline.py`는 **선형 파이프라인**이다. 각 단계를 순서대로 실행하고, `PipelineStageError` 발생 시 `_halt()`로 중단하며 `StageTrace`를 남긴다.

**다만 완전히 "독립 실행"은 아니다.** PR #20이 **국소적 피드백 루프**를 추가했다:
- validator 결과가 `profile.min_validated_documents` 미달 → 제외 URL을 갱신해 collector 재실행 (`max_validation_recollection_attempts` 한도)
- analyzer 결과가 `min_analyzed_documents` 미달 → 동일하게 재수집
- `WebSearchContext.validation_feedback`으로 "무엇이 부족했는지"를 다음 수집에 전달

즉 **수집·검증 구간에는 이미 자기교정 루프가 있다.** 반면 **synthesis 이후(report_planner → generator → adapter → layout)에는 어떤 검증·재작성 루프도 없다.** 최종 산출물이 원 질문에 답하는지, 목적에 맞는 형태인지 확인하는 단계가 존재하지 않는다.

### 결론: **지금 발견된 문제들은 오케스트레이션 문제가 아니다.**

근거:

| 발견된 문제 | 성격 | 오케스트레이션으로 해결되나? |
|---|---|---|
| 청중 구조가 목적을 덮어씀 | `planner.py`의 `if profile.report_structure:` 분기 하나 | ❌ 해당 분기를 고쳐야 함 |
| 뷰가 sections를 안 읽음 | 뷰가 그 데이터를 참조하지 않음 | ❌ 뷰를 고쳐야 함 |
| 수치 추출 실패 | 정규식이 `누적`을 허용 안 함 | ❌ 추출기를 고쳐야 함 |
| `chart` 블록 배선 없음 | `data`/`config` 미전달 | ❌ 배선해야 함 |

**전부 특정 단계 내부의 결정론적 로직 결함이며, 단계 간 정보 전달의 문제가 아니다.** 오히려 상류(planner의 `_content_backed_sections`, `section_evidence_map`)는 이미 정교하게 만들어져 있고 **하류가 그것을 안 읽는 것**이 문제다. 감독 레이어를 얹으면 이 결함들이 가려질 뿐 사라지지 않으며, LLM 호출 비용과 비결정성만 늘어난다.

**단, 오케스트레이션이 필요한 영역이 하나 있다**: 현재 **최종 산출물이 원 질문에 답하는지 확인하는 주체가 없다.** "매출 추이"를 물었는데 추이 차트 없이 SWOT이 나가도 아무도 이의를 제기하지 않는다. 이는 위 4개 결함을 다 고쳐도 남는 구조적 공백이다.

### 옵션 (구현 아님, 검토용)

#### 옵션 A — 최종 산출물 검증 단계 (결정론적)
`layout_generator` 뒤에 규칙 기반 검증 단계를 둔다. "질문이 추이형인데 시계열 블록이 없다", "목적이 원인분석인데 원인 블록이 없다" 같은 **명시적 규칙**으로 점검하고, 실패 시 재구성하거나 리포트에 한계로 명시.

- 장점: 결정론적·테스트 가능·비용 0·기존 `content_quality_validator` 패턴과 일관
- 단점: 규칙을 사람이 다 열거해야 함. 예상 못 한 질문 유형은 못 잡음
- 적합도: **현재 문제에 가장 잘 맞음.** 위 4개 결함이 재발했을 때 조기에 잡아주는 안전망

#### 옵션 B — 리포트 감독자 (LLM, 사후 1회)
완성된 리포트 + 원 질문을 LLM에 넘겨 "이 리포트가 질문에 답하는가, 빠진 시각화는 무엇인가"를 판정하고 부족하면 재작성 지시.

- 장점: 규칙 열거 불필요, 예상 못 한 유형에도 대응
- 단점: 질문당 LLM 호출 1회 추가(비용·지연), 비결정적이라 테스트가 어려움, "판정 자체가 틀릴" 위험
- 적합도: 옵션 A로 잡히지 않는 잔여 케이스용 **2차 방어선**. 단독 도입은 권장하지 않음

#### 옵션 C — 최상위 계획 에이전트 (전면 재구조화)
파이프라인 진입 시 LLM이 "이 질문에는 어떤 수집·분석·시각화가 필요한가"를 먼저 계획하고, 각 단계 출력을 검증하며 진행.

- 장점: 가장 유연. 질문마다 진짜로 다른 실행 경로가 가능해져 제품 차별점과 방향이 일치
- 단점: **현 아키텍처의 계약 격리 원칙(`CLAUDE.md`)과 정면 충돌**. 재작성 범위가 매우 큼. 비용·지연·비결정성 최대. 지금의 결함들은 이걸로도 안 고쳐짐(여전히 planner/view를 고쳐야 함)
- 적합도: **현재로선 시기상조.** 위 4개 결함을 고치고 실제 통계를 축적한 뒤 재검토할 사안

### 권고

**오케스트레이션 도입은 보류하고, [질문 1~3]의 결함부터 고친다.** 그 뒤 **옵션 A**(결정론적 최종 검증)를 얇게 추가해 재발을 막는 것을 권장한다. 옵션 B는 A로 부족함이 실측된 후에, 옵션 C는 제품 방향이 확정된 후에 재검토.

---

## 종합 권고 순서

| 순위 | 조치 | 근거 질문 |
|---|---|---|
| 1 | **정책 결정**: 청중 고정 구조 vs 보고목적, 무엇이 섹션을 정하는가 | Q3 |
| 2 | 뷰가 `report_plan.sections`를 따르도록 전환 | Q3 |
| 3 | 수치 추출기 확장 (라벨·수식어·YoY) | Q1 |
| 4 | 렌더링 경로 일원화 (`blocks/` 레지스트리 vs `components.py`) | Q2 |
| 5 | `current_status` 전용 레시피 | Q3 |
| 6 | 실행 결과 영속화 → 다음 진단의 통계 확보 | Q1 |
| 7 | 원인 트리 / 과거vs현재 계약 확장 (라이브러리 도착 시점에 맞춤) | Q2 |
| 8 | 결정론적 최종 검증 단계 (옵션 A) | Q4 |

**1번은 설계 의사결정이라 구현 전 합의가 필요하다.** 나머지는 기술적 수정이다.
