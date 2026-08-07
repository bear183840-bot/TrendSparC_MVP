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
| 2.3 `ForecastLineCard` | 실적/전망 구분 | `MetricPoint.is_forecast: bool`. 지금은 period 문자열에 "(전망)"이 섞여 있을 뿐이라 파싱에 의존 |
| 2.4 `LandscapeSplit` 도넛 | "전체의 구성비"라는 표시 | 도넛은 합이 100%인 분할이어야 한다. 지금 `ComparisonPoint`에는 그 값들이 한 모집단의 분할인지 표시할 방법이 없어, 무관한 %를 합쳐 그릴 위험이 있다 |
| 3.1 `DriverBarList` | `value: number` (중요도) | 순위에서 역산한 %는 **의도적으로 제거**했다(근거 없는 정밀도). 실제 중요도를 근거에서 받아야 하며, AI 판단이면 "AI 판단" 표기 필수 — 진단 리포트 Step 2-1 |
| 5.1/5.2 `Timeline*` | `status: done/active/todo` | 지금 타임라인은 "날짜 있는 근거"일 뿐 진행 상태 개념이 없다 |
| 6.3 `CompetitorPanels` | 경쟁사별 process + importance + 도넛 | 위 세 가지의 합성. 각각이 갖춰져야 가능 |
| 7.1/7.2 `RootCauseTree` | 원인 간 부모-자식 | `GroundedClaim.parent_claim_id`. **가장 자주 요청됐고 가장 오래 막혀 있는 항목** — Step 2-1 |
| 8.3 `ActionImpactList` | 임팩트 **수치**(진행바용) | 지금 `ActionImpact.expected_impact`는 **문장**이다. 근거가 "이탈률 5%p 개선"이라 말해도 막대 길이로 쓸 수치는 따로 없다. 근거가 수치를 말한 경우에만 채우는 `impact_value: float \| None` 추가가 필요 |

## 3축 데이터 문제 (별도)

블록과 무관하게, 목표 질문 중 두 개가 **3축 데이터**를 요구한다:

- 질문 1: 연령대 × 매체 × reach
- 질문 5: 회사 × 지표 × 값

`MetricPoint`는 (label, period, value, unit) 2축이라, 지금은 `period`에 연령대나
회사명을 넣는 편법으로만 표현된다. 그래서 `is_time_period()` 같은 방어 로직이
계속 필요해졌다. 3축을 정식으로 담으려면 `MetricPoint.dimension`(이 축이
시간인지 대상인지) 또는 별도 `MatrixPoint` 계약이 필요하다.

## 구현 순서 제안

1. **파생 계층 먼저** — KPI delta/spark, trend series. 계약 변경 0으로 블록
   6종이 살아난다.
2. **`MetricPoint.is_forecast` + `impact_value`** — 각각 한 필드, 블록 2종.
3. **Step 2-1 관계 필드** — `parent_claim_id`, `importance`. 블록 3종
   (RootCauseTree, DriverBarList, CompetitorPanels 일부).
4. **3축 계약** — 목표 질문 1·5를 제대로 답하려면 필요.

## 지키고 있는 원칙 (블록 구현 시 유지할 것)

- 데이터가 그 모양일 때만 그 블록을 쓴다. 3개 시점이 없으면 라인이 아니라 막대,
  등급이 없으면 레이더가 아니라 표.
- 빈 칸은 정직한 결과다. "관련 데이터 수집 필요"로 메우지 않는다.
- 순위에서 역산한 %처럼 **측정값처럼 보이지만 정보가 없는 수치**를 만들지
  않는다.
- 색만으로 등급을 표현하지 않는다(명세 6번 지침과 동일).
