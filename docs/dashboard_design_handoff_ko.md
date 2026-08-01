# TrendSparC 최종 대시보드 디자인 핸드오프

대상: 정민님 및 대시보드 시안을 만드는 디자이너/GPT

## 1. 제품을 한 문장으로 설명하면

TrendSparC는 사용자의 질문과 첨부문서를 받아 관련 공개 소스를 실제로 수집·분석하고, 질문 목적과 청중에 맞는 의사결정 보고서를 생성하는 AI 트렌드 인텔리전스 제품이다.

검색 결과 목록을 보여주는 뉴스 서비스가 아니다. 사용자가 화면을 본 뒤 다음 세 가지를 빠르게 판단할 수 있어야 한다.

1. 지금 가장 중요한 결론은 무엇인가?
2. 그 결론을 뒷받침하는 근거와 불확실성은 무엇인가?
3. 그래서 무엇을 검토하거나 실행해야 하는가?

## 2. 이번 디자인 요청의 범위

사용자가 제공하는 구체적인 질문 3~4개에 대해 질문별로 완성도 높은 최종 대시보드 화면을 1개씩 만든다.

- 질문마다 별도 대시보드를 만든다.
- 3~4개 화면은 같은 TrendSparC 제품군으로 보여야 한다.
- 질문의 `report purpose`와 `audience`에 따라 정보 우선순위와 컴포넌트가 달라져야 한다.
- 단순 와이어프레임이 아니라 개발자가 구현 기준으로 사용할 수 있는 최종 UI 시안이어야 한다.
- 데스크톱 기준 1440px 화면을 우선한다. 핵심 반응형 규칙도 함께 정의한다.

가능하면 네 가지 보고 목적을 각각 한 번씩 포함한다.

| 보고 목적 | 사용자가 묻는 것 | 대표 UI 초점 |
|---|---|---|
| `current_status` | 현재 시장·기업·기술 상태는 어떤가? | 현황 요약, 핵심 변화, 관찰 지표 |
| `issue_response` | 어떤 위험이 있고 어떻게 대응해야 하는가? | Issue → Impact → Action |
| `future_business` | 앞으로 어떤 사업 기회가 있는가? | Signal → Opportunity → Roadmap |
| `root_cause` | 문제가 왜 발생했으며 무엇을 고쳐야 하는가? | Problem → Cause → Impact → Improvement |

질문이 3개라면 `current_status`, `issue_response`, `future_business`를 우선하고, `root_cause`는 선택 사항으로 둔다.

## 3. 입력과 처리 흐름

```text
질문 + 청중 + 선택 섹터 + 첨부자료
  → Entity/Intent 추출
  → Sector Router (특정 섹터 신호가 없으면 general)
  → Report Purpose 분류
  → 관련 소스 Top 6 선정
  → 웹·첨부문서 수집/정제/검증
  → 문서별 분석
  → Synthesis
  → Report Generator
  → Audience Adapter
  → Layout Generator
  → Dashboard UI
```

첨부문서는 웹 문서보다 낮은 우선순위의 참고자료가 아니다. 별도 문서로 분석되며 웹 문서와 동일한 근거 단위로 취급된다.

네이버 뉴스는 모든 섹터에서 `core`로 등록된 핵심 검색 채널이다. 다만 네이버 자체가 원 발행처는 아니므로 사실 신뢰도는 개별 기사 원문 기준으로 판단한다.

## 4. UI가 받게 되는 핵심 출력

최종 보고서의 중심 계약은 아래와 같다.

```json
{
  "request_id": "req_xxx",
  "sector_id": "sk_broadband",
  "audience_id": "executive",
  "purpose_id": "issue_response",
  "title": "보고서 제목",
  "executive_summary": "질문에 대한 최상위 결론",
  "source_count": 6,
  "generation_mode": "openai",
  "limitations": [],
  "sections": [
    {
      "section_id": "issue",
      "title": "Issue",
      "summary": "이 섹션만의 완성 문장",
      "key_points": ["핵심 사실"],
      "evidence": ["근거 문장 [doc_id=...]"],
      "risks": ["리스크"],
      "opportunities": ["기회"],
      "actions": ["권고 행동"],
      "monitoring_indicators": ["계속 관찰할 지표"],
      "confidence": "high [doc_id=...]"
    }
  ]
}
```

`layout.blocks`에는 위 보고서가 실제 화면 순서로 들어온다.

```json
{
  "format": "pdf",
  "render_target": "pdf",
  "blocks": [
    {"section": "executive_summary", "content": {}},
    {"section": "issue", "content": {}},
    {"section": "impact", "content": {}},
    {"section": "response_actions", "content": {}}
  ]
}
```

섹션의 존재 여부와 순서는 질문 목적과 청중에 따라 달라진다. 화면을 특정 섹션 네 개에 고정하지 말고, 공통 블록 시스템으로 설계한다.

## 5. 반드시 표현해야 하는 정보 계층

### 5.1 상단 컨텍스트 바

- 사용자가 입력한 원문 질문
- 감지/선택된 섹터
- 보고 목적
- 청중
- 분석 문서 수
- 첨부문서 유무
- 생성 상태 또는 생성 모드

질문은 페이지 제목보다 중요한 분석 컨텍스트다. 사용자가 “내가 무엇을 물었는지”를 항상 확인할 수 있어야 한다.

### 5.2 Executive Summary

- 화면에서 가장 먼저 읽히는 결론
- 2~4문장 이내의 높은 정보 밀도
- 주요 위험 또는 기회가 있으면 작은 상태 배지로 연결
- 근거 부족 시 이를 숨기지 않고 `limitations` 또는 confidence로 표시

### 5.3 목적별 본문

각 섹션은 같은 요약을 반복하지 않는다. 아래처럼 목적에 맞는 다른 시각 구조를 사용한다.

| 데이터 | 적합한 표현 |
|---|---|
| `key_points` | 핵심 포인트 카드, 우선순위 리스트 |
| `business_impact` | 영향 요약 카드, 영향 범주 태그 |
| `risks` | 위험 카드, 위험 목록, 근거 연결 |
| `opportunities` | 기회 카드, 기회 영역 맵 |
| `actions` | 실행 항목 리스트, 단계별 체크리스트 |
| `monitoring_indicators` | Watchlist, 모니터링 체크포인트 |
| `evidence` | 근거 패널, 접을 수 있는 Evidence Drawer |
| `confidence` | High/Medium/Low 배지 및 설명 툴팁 |
| `limitations` | 경고/주의 패널 |

### 5.4 근거와 신뢰도

- 주요 결론 옆에서 근거를 열어볼 수 있어야 한다.
- `[doc_id=...]`는 사용자에게 그대로 크게 노출하기보다 “근거 보기” 인터랙션의 연결 키로 사용한다.
- `confidence=low` 또는 limitations가 있으면 긍정적 결론보다 눈에 덜 띄게 숨기지 않는다.
- 서로 충돌하는 근거가 생길 수 있으므로 향후 `conflicting evidence` 상태를 수용할 수 있어야 한다.

### 5.5 액션

- 액션 텍스트는 다른 분석 문장과 시각적으로 구분한다.
- 실행 순서를 표현할 수 있으나, 백엔드에 없는 담당자·기한·진행률을 임의 생성하면 안 된다.
- 향후 owner/due date 필드가 추가될 공간은 확보해도 된다.

## 6. 청중별 디자인 차이

| audience_id | 성격 | 화면 밀도와 우선순위 |
|---|---|---|
| `executive` | 팀장·의사결정자 | 결론, 핵심 시사점, 위험/기회, 권고 행동을 우선. 압축적 구성 |
| `management` | 상위 경영진 | 전략 방향, 경쟁 위치, 이사회 수준 위험. 세부 기술정보 최소화 |
| `practitioner` | 실무자 | 근거, 모니터링 지표, 상세 분석, 실행 체크리스트를 충분히 노출 |
| `external` | 외부 파트너·고객 | 공개 사실과 시장 맥락 중심. 내부 전략·민감 정보 표현 금지 |

같은 질문이어도 청중이 다르면 카드 순서, 텍스트 밀도, 기본 펼침 상태가 달라져야 한다.

## 7. 공통 화면 구조 권장안

```text
┌──────────────────────────────────────────────────────────────┐
│ TrendSparC / Sector badge / 분석 메타 / 내보내기             │
├──────────────────────────────────────────────────────────────┤
│ 사용자 질문                                                  │
│ Executive Summary                            Confidence      │
├──────────────────────────────────────────────────────────────┤
│ 핵심 목적별 블록: Issue / Status / Opportunity / Problem     │
├───────────────────────┬──────────────────────────────────────┤
│ Impact 또는 Risk      │ Opportunity 또는 Key Points          │
├───────────────────────┴──────────────────────────────────────┤
│ Recommended Actions / Improvement Plan / Roadmap             │
├──────────────────────────────────────────────────────────────┤
│ Monitoring Indicators                                        │
├──────────────────────────────────────────────────────────────┤
│ Evidence & Sources / Limitations                              │
└──────────────────────────────────────────────────────────────┘
```

모든 질문에서 이 순서를 강제하지 않는다. 목적에 따른 대표 순서는 다음과 같다.

- 현황: Summary → Current Situation → Market Status → Outlook → Monitoring
- 대응: Summary → Issue → Impact → Action → Evidence
- 미래사업: Summary → Trend → Opportunity → Investment Signal → Roadmap
- 원인분석: Summary → Problem → Root Cause → Impact → Improvement

## 8. 상태 화면도 디자인해야 한다

최종 결과 화면만 만들면 구현 시 빈틈이 생긴다. 최소한 다음 상태를 정의한다.

- 질문 입력 전
- 수집·분석 진행 중
- 일부 소스 수집 실패, 분석은 완료
- 문서가 0건이거나 근거 부족
- 첨부문서 추출 실패/미지원
- OpenAI 보고서 생성 실패 후 규칙 기반 fallback
- 정상 완료

일부 실패는 전체 오류 화면이 아니다. 결과를 보여주면서 limitations를 함께 노출하는 방식이 기본이다.

## 9. 현재 백엔드에 없는 데이터

아래 정보는 현재 계약에 없으므로 최종 UI에서 실제 값처럼 만들지 않는다.

- 액션 담당자, 마감일, 진행률
- 정량적인 위험 확률과 금액 영향
- 차트용 시계열 수치
- 문서 저자
- 최종 보고서에 직접 포함된 출처 URL과 원문 제목
- 섹션별 사용자 편집 이력

시안에서 필요하면 `향후 확장 필드` 또는 명확한 placeholder로 표시하고 개발 요구사항으로 따로 적는다. 특히 실제 수치가 없는 상황에서 임의의 막대그래프·선그래프·퍼센트를 만들지 않는다.

## 10. 질문별 최종 시안 요청 템플릿

질문마다 아래 템플릿을 한 번씩 작성해 정민님에게 전달한다.

```text
[Dashboard 1]
질문:
선택 섹터: 자동 감지 / sector_id
청중: executive / management / practitioner / external
예상 보고 목적: current_status / issue_response / future_business / root_cause
첨부자료: 없음 / 있음(종류만 기재)
특히 확인하고 싶은 의사결정:
디자인에서 강조할 점:
```

각 질문에 대해 다음 산출물을 요청한다.

1. 최종 데스크톱 대시보드 1안
2. 섹션 순서와 각 컴포넌트 선택 이유
3. 정상·로딩·부분실패·근거부족 상태
4. 반응형 축소 규칙
5. 개발 핸드오프용 spacing, typography, color, component 상태

## 11. 디자인 원칙

- SK 계열사별 로고를 임의 제작하거나 변형하지 않는다.
- 섹터별로 완전히 다른 제품처럼 보이게 만들지 않는다.
- 브랜드 컬러는 강조에 제한적으로 사용하고 긴 보고서의 가독성을 우선한다.
- 핵심 결론, 근거, 액션의 시각적 관계가 장식보다 중요하다.
- 카드가 많다는 이유만으로 모든 데이터를 카드로 만들지 않는다.
- 표는 비교가 필요할 때, 타임라인은 순서가 있을 때, 차트는 실제 수치가 있을 때만 사용한다.
- 한 화면에서 가장 중요한 메시지는 하나여야 한다.

## 12. 완료 판단 기준

- 질문과 보고 목적이 화면만 봐도 이해되는가?
- Executive Summary와 각 섹션이 같은 내용의 반복처럼 보이지 않는가?
- 근거와 불확실성에 접근할 수 있는가?
- 사용자가 다음 행동을 판단할 수 있는가?
- 질문 3~4개의 화면이 하나의 제품 디자인 시스템으로 연결되는가?
- 백엔드에 없는 데이터가 사실처럼 표현되지 않았는가?
