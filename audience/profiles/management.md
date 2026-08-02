---
display_name: Senior Management
tone: strategic, high-level, minimal jargon
detail_level: highlight_only
focus:
  - strategic_direction
  - competitive_position
  - board_level_risk
format_preference: pdf
report_structure:
  - overview
  - opportunity
  - risk
  - strategic_recommendation
  - sources
---

경영진 청중 프로필입니다. Broad한 시각, 주요 결정사항, 앞으로의 전망에 관심이
많으며 결론과 핵심 성과를 우선 봅니다. 기술적 세부사항은 최소화하고, 전략적
방향성과 경쟁 구도, 경영 판단에 영향을 주는 리스크 위주로 극도로 압축된
형태로 제공합니다.

1. **정보 밀도 (Information Density)**
   - 세부 이슈 정보보다는 핵심 성과, 사업 영향도, 전략적 시사점을 중심으로
     요약한다. 기업의 성장과 매출, 비용 절감 효과 등 경영 성과와 직결되는
     정보 위주로 제공한다.

2. **관심사 초점 (What they care about)**
   - "이 결과가 회사의 미래 성장과 경쟁력에 어떤 영향을 주는가"를 중심으로
     재배열한다. 주요 의사결정 포인트와 중장기 전망, 기대 효과를 우선적으로
     제시한다.

3. **용어 수준 (Vocabulary)**
   - 전문 용어와 기술적 설명을 최소화하고, 경영 관점의 비즈니스 언어를
     사용한다. 핵심 결론과 인사이트를 한눈에 이해할 수 있도록 간결하게
     표현한다.

4. **분량·구조 (Length & Structure)**
   - Executive Summary를 가장 앞에 배치하고, 결론부터 제시하는 역피라미드
     구조를 적용한다. 핵심 성과(KPI), 시장 전망, 예상 효과를 대시보드형 요약
     차트 중심으로 구성한다.

5. **행동 유도 (Call to action)**
   - 보고서 맨 마지막은 '전략적 제언(Strategic Recommendation)' 또는
     '향후 추진 방향(Strategic Next Steps)'으로 마무리한다. 기대 효과와 투자
     가치, 향후 추진 전략을 함께 제시한다.

6. **불변 원칙 (Non-negotiable)**
   - 긍정적인 성과뿐 아니라 주요 리스크와 불확실성도 함께 제시한다. 정량적
     데이터 근거를 기반으로 설명하며, 확인되지 않은 내용을 확정적으로
     표현하지 않는다.

7. **분석 관점 우선순위** (`DocumentAnalysis`의 8개 필드 기준)
   - `risk`/`opportunity`를 전략적 시사점 한 줄로 극도 압축.
   - `recommended_actions`는 "전략적 제언" 문구로 재구성해 제시.
   - `business_impact`는 KPI/매출 단위로 정량화해서만 노출.
   - `evidence`/`monitoring_indicators`/`action_level`은 본문에서 생략, 필요 시
     부록으로만 첨부.
   - `analysis_confidence`가 낮은 항목은 반드시 별도 강조 (불확실성 명시
     원칙, `prompts/global_system_prompt.md` 원칙 1·3과 연결).
