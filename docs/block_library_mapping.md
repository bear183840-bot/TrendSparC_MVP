# 블록 라이브러리 ↔ 파이프라인 계약 매핑

블록 라이브러리는 **디자인 레퍼런스**다 - 컴포넌트를 그대로 이식하라는 뜻이
아니라, 블록별 시각 어휘(무엇을 어떤 모양으로 보여주는가)를 참고하라는 것.
명세 자체는 React/TSX로 쓰여 있지만 우리 렌더러는 Streamlit이고, 그대로 둔다.

이 문서가 답하는 것은 하나다: **그 시각 어휘 중 어디까지를 우리 데이터가
실제로 채울 수 있는가.** 데이터가 없는 모양을 먼저 만들면 화면에 영원히
빈칸으로 남는다.

## 지금 데이터로 바로 채워지는 블록

| 블록 | 먹이는 계약 | 비고 |
|---|---|---|
| 4.1 `SwotCard` | `synthesis.{strengths,weaknesses,opportunities,risks}` | 근거 있는 사분면만 그린다(2개 미만이면 블록 생략) |
| 4.2 `DualFrameCard` | 위와 동일, 2분면 | |
| 6.1 `ComparisonMatrix` | `ComparisonPoint.{entity,criterion,level}` | `level`이 정확히 low/medium/high — **명세와 1:1** |
| 6.2 `ComparisonTable` | `ComparisonPoint.{entity,criterion,value}` | |
| 8.1 `StrategyList` | `recommended_actions` + `GeneratedReport.action_impacts` | 임팩트는 근거가 말한 경우만, 나머지는 빈칸 |
| 8.2 `ActionList` | `recommended_actions` | |
| 9.1/9.2 `SourceList` | `SynthesisSource` + `doc_url_map` | name/note/href 모두 있음 |
| 2.2 `TrendCompareCard` | 같은 unit·period를 공유하는 2개 label의 `metric_points` | |
| 3.2/3.3 `BarChartCard` | `metric_points` (2개 이상 period 또는 subject) | |

## 파생 계층만 만들면 되는 블록 (계약 변경 불필요)

| 블록 | 필요한 파생 | 어떻게 |
|---|---|---|
| 1.1~1.6 `Kpi*` 전체 | `delta` | 같은 label의 두 period 값에서 계산. **표시할 때 "계산값"임이 드러나야 한다** — 근거가 말한 증감률이 따로 있으면 그것을 우선 |
| 1.4 `KpiSparkGrid` | `spark: number[]` | 같은 label의 period 정렬 후 value 배열 |
| 1.6 `KpiStatusBar` | 정성 상태값 | `ComparisonPoint.level` 또는 `action_level` |
| 2.1 `TrendLineCard` | `series` | `metric_points` label별 그룹 |
| 2.1 `AiInsightButton` | 인사이트 텍스트 | `SynthesisClaim` 중 해당 metric을 참조하는 것 (`evidence_synthesis_claim_id`로 이미 연결됨) |

## 계약 변경이 필요한 블록

| 블록 | 없는 것 | 필요한 변경 |
|---|---|---|
| ~~2.3 `ForecastLineCard`~~ | ~~실적/전망 구분~~ | **완료.** `MetricPoint.is_forecast` 추가. 모델이 표시하되 근거의 전망 표현(전망/예상/목표/추정/계획/가이던스)이 실제로 있을 때만 인정한다. 관측 구간은 실선, 전망으로 넘어가는 구간은 점선 + 범례, KPI 헤드라인은 **관측된 최신값**을 쓴다 |
| ~~2.4 `LandscapeSplit` 도넛~~ | ~~"전체의 구성비"라는 표시~~ | **완료.** `MetricPoint.share_of`(그 값이 어느 전체의 일부인지)를 근거가 그렇게 서술한 경우에만 채운다. 그리기 전에 ① 같은 전체를 가리키는 항목이 2개 이상 ② 단위가 % ③ 합이 100 이하 — 셋을 모두 확인한다(중복응답 설문은 합이 100을 넘어 걸러진다). 합이 100에 못 미치면 남는 부분은 "출처에 명시되지 않음"으로 비워 두고 '기타'를 만들지 않는다 |
| ~~3.1 `DriverBarList`~~ | ~~`value: number` (중요도)~~ | **완료.** `GroundedClaim.importance` + `importance_basis`. 이유 없는 점수는 통째로 폐기되고, 화면에는 "AI 판단" 배지와 이유 툴팁이 항상 붙는다. 막대는 상위 항목이 아니라 100 기준으로 스케일한다 |
| ~~5.1/5.2 `Timeline*`~~ | ~~`status: done/active/todo`~~ | **완료. 계약 변경 없이 파생.** 문서가 실제로 쓴 표현("추진 중"/"출시 예정"/"완료했다")이 우선하고, 아무 말도 없을 때만 `as_of_date` 대비 시점으로 정한다. 둘 다 없으면 **진행**으로 남는다 — 날짜만으로 완료를 주장하지 않는다 |
| 6.3 `CompetitorPanels` | 경쟁사별 process + importance + 도넛 | 위 세 가지의 합성. 각각이 갖춰져야 가능 |
| ~~7.1/7.2 `RootCauseTree`~~ | ~~원인 간 부모-자식~~ | **완료.** `GroundedClaim.parent_claim_id` → `SynthesisClaim.parent_synthesis_claim_id`. 검증을 통과한 같은 문서의 claim만 부모가 될 수 있고, 자기 자신·순환은 끊는다. 2단까지만 그린다 |
| ~~8.3 `ActionImpactList`~~ | ~~임팩트 **수치**(진행바용)~~ | **완료.** `ActionImpact.impact_value` / `impact_unit`. 인용 문장에 그 숫자가 실제로 있을 때만 인정하고, 문장만 있는 행은 막대 없이 문장만 남는다 |

## 3축 데이터 문제 (별도)

블록과 무관하게, 목표 질문 중 두 개가 **3축 데이터**를 요구한다:

- 질문 1: 연령대 × 매체 × reach
- 질문 5: 회사 × 지표 × 값

**해결됨.** `MetricPoint.subject`를 추가해 (label, subject, period) 3축이 됐다.
주체가 2개 이상이면 기간이 무엇이든 comparison으로 분류되고, 막대 행 라벨은
실제로 변하는 축을 따라간다(둘 다 변하면 "KT (2024년)"처럼 둘 다 표기).
`period`는 다시 날짜 전용이므로 `is_time_period()`는 방어가 아니라 본래 용도로
쓰인다.

## 구현 순서 제안

1. ~~**파생 계층**~~ — 완료 (KPI delta/spark, 차트 근거 캡션).
2. ~~**`MetricPoint.is_forecast` + `impact_value`**~~ — 완료.
3. ~~**Step 2-1 관계 필드**~~ — 완료 (`parent_claim_id`, `importance`).
4. ~~**3축 계약**~~ — 완료 (`MetricPoint.subject`).

남은 것: `CompetitorPanels` 하나뿐이며, 이는 새 계약이 아니라 이미 만들어진
도넛·중요도·원인 트리를 경쟁사별로 묶는 레이아웃 작업이다.

관계 필드는 현재 **sk_broadband 어댑터에만** 구현돼 있다(계획대로). 다른 섹터는
스키마에 같은 세 필드를 추가하고 `_verified_relations()`를 호출하면 그대로
동작한다 — `common/contracts.py`는 섹터 무관이라 계약 변경은 필요 없다.

## 지키고 있는 원칙 (블록 구현 시 유지할 것)

- 데이터가 그 모양일 때만 그 블록을 쓴다. 3개 시점이 없으면 라인이 아니라 막대,
  등급이 없으면 레이더가 아니라 표.
- 빈 칸은 정직한 결과다. "관련 데이터 수집 필요"로 메우지 않는다.
- 순위에서 역산한 %처럼 **측정값처럼 보이지만 정보가 없는 수치**를 만들지
  않는다.
- 색만으로 등급을 표현하지 않는다(명세 6번 지침과 동일).


## 변형 선택 규칙 (2026-08-09)

정민님 SVG는 **기본형**이고, 실제로 어떤 변형을 그릴지는 **들어온 자료의 종류와
개수**가 정한다. 플래그나 설정이 아니라 데이터가 고르는 구조이므로, 새 질문이
와도 그 질문에 맞는 변형이 자동으로 선택된다.

| 블록 | 변형 | 무엇이 고르는가 |
|---|---|---|
| KPI | 카드 그리드 / 행 나열 | 지표 3개 이상이면 그리드, 1~2개면 행(빈 칸이 "자료 없음"으로 읽히지 않게) |
| KPI | 스파크라인 유무 | 관측 시점 3개 이상일 때만. 2개는 옆의 증감이 이미 다 말한다 |
| KPI | 전망 배지 | `is_forecast`가 근거의 전망 표현으로 확인됐을 때 |
| KPI | 상태 바 | 수치가 아니라 등급(`level`)만 있을 때 |
| Line/Area | 단일 추세 / 2계열 / 실적·전망 / Landscape | 계열 수, `is_forecast`, 구성비(`share_of`) 동반 여부 |
| Bar | 가로 2개(전후) / 세로 컬럼(3개 이상) / 묶음(주체×항목) | 비교 대상 수와 축 개수 |
| Timeline | 가로 / 세로 | 항목 5개 이하 + 짧은 라벨이면 가로, 문장이 길면 세로 |
| Timeline | 완료/진행/예정 | 문서가 쓴 표현이 우선, 없으면 기준일 대비 시점 |
| Matrix | 2×2 / 1×2 | 근거가 채운 사분면 수(1개면 블록 자체를 안 그림) |
| Table | 등급 도트 / 값 | `level`이 있으면 도트+등급어, 없으면 값 그대로 |
| Cause | 3열 맵 / 원인 트리(최대 3단) | `parent_claim_id` 연결이 있으면 트리, 없으면 3열 |
| Action | 임팩트 문장 / 임팩트 막대 | 출처가 크기를 말했을 때만 막대 |
| Donut | 슬라이스 수 / 미명시 잔여 | 합이 100 미만이면 남는 부분을 비워 두고 명시 |

**`CompetitorPanels`** (2026-08-09 구현): 경쟁사별로 ① 문서가 등급을 매긴 항목
② `subject`가 그 경쟁사인 수치 ③ 그 경쟁사의 구성비 슬라이스 — 이 셋 중 **2가지
이상이 확인될 때만** 패널이 뜬다. 아트워크의 회사별 프로세스 레일은 **의도적으로
뺐다**: claim을 경쟁사 시점에 묶는 데이터가 없어서, 리포트 자체의 연표로 그리면
우리 회사 이력을 경쟁사 것으로 붙이게 된다.

**`AiInsightButton`** (2026-08-09 구현): 상시 캡션 → 아트워크의 테두리 컨트롤로.
열면 검증된 claim과 출처가 나온다. 연결된 claim이 없으면 컨트롤 자체가 없다.
