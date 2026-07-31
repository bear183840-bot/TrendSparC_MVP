# SK Broadband Sector

Status: `active`.

SK Broadband 섹터는 TrendSparC의 1차 발표 기준 섹터다. 사용자가 직접 섹터를 고르지 않아도 IPTV, B tv, OTT, FAST, 미디어 플랫폼, 콘텐츠 유통, 초고속 인터넷, 네트워크 인프라, AI 미디어, 방송·통신 정책 관련 질문이면 라우터가 이 섹터로 연결할 수 있도록 설계한다.

이 문서는 SK Broadband 섹터의 범위, 라우팅 용어, 분석 기준, Source 구성, 대상별 강조 포인트를 정의한다.

## 1. Sector 범위

### 포함하는 내용

- IPTV 및 유료방송 시장
- B tv 및 미디어 플랫폼 서비스
- OTT 및 스트리밍 서비스
- FAST(Free Ad-supported Streaming TV)
- Connected TV 및 디지털 광고
- 콘텐츠 유통 및 제작 생태계
- AI 기반 미디어 서비스
- AI Recommendation, AI Search, Content Discovery
- 방송·통신 융합 서비스
- 초고속 인터넷(Broadband)
- Fiber Network, FTTH, Wi-Fi
- CDN(Content Delivery Network)
- Edge Computing, MEC
- IDC, Data Center, Cloud, MSP, B2B ICT
- 방송·통신 정책 및 규제
- 망 사용료, 저작권, 개인정보, AI Regulation

### 포함하지 않는 내용

- 반도체 제조 기술
- 메모리 반도체 시장
- AI 칩 개발
- AI 모델 자체 연구(LLM 개발)
- 일반 제조업
- 금융 산업
- 바이오 산업
- 자동차 산업
- 게임 산업(미디어·콘텐츠 관점 제외)
- 스마트팩토리

## 2. 핵심 키워드 및 용어

### Business

- IPTV
- B tv
- 유료방송
- OTT
- FAST
- Streaming
- Connected TV
- Media Platform
- Content Distribution
- Digital Media
- Broadband
- Enterprise Network
- IDC
- Data Center
- Cloud
- MSP
- B2B ICT

### AI

- AI
- Generative AI
- AI Agent
- LLM
- Video AI
- AI Search
- AI Recommendation
- Hyper-personalization
- Recommendation System
- Content Discovery
- AI Media
- AI Advertisement

### Network

- Fiber
- Fiber Network
- FTTH
- Broadband
- Wi-Fi
- Edge Computing
- CDN
- MEC
- 5G
- 6G
- Network Infrastructure
- Network Virtualization
- SDN
- NFV

### Media

- OTT
- Netflix
- Disney+
- YouTube
- TVING
- Wavve
- Coupang Play
- Apple TV+
- FAST
- Ad-supported Streaming
- Premium Content
- Original Content
- Sports Rights
- Content Licensing

### Policy

- 방송통신위원회
- 과학기술정보통신부
- KCC
- MSIT
- 방송 규제
- 망 사용료
- Net Neutrality
- 저작권
- 개인정보
- Data Privacy
- AI Regulation
- Digital Policy

### Market

- ARPU
- Subscriber
- Market Share
- Cord Cutting
- Subscriber Growth
- Churn Rate
- Revenue
- Advertising
- Media Industry
- Telecom Industry

### Competition

- KT
- KT Genie TV
- LG U+
- U+tv
- Netflix
- Disney+
- YouTube
- TVING
- Wavve
- Coupang Play
- Amazon Prime Video
- Apple TV+
- Comcast
- Charter
- Verizon
- AT&T

### Technology

- Cloud Gaming
- XR
- AR
- VR
- Digital Twin
- Smart Home
- IoT
- Edge AI
- AI Video Analytics
- Video Compression
- HEVC
- AV1

### 주요 기업

#### 국내

- SK브로드밴드
- KT
- LG U+
- Wavve
- TVING
- Coupang Play
- CJ ENM
- SBS
- KBS
- MBC

#### 글로벌

- Netflix
- Disney+
- Amazon Prime Video
- Apple TV+
- YouTube
- Hulu
- Warner Bros. Discovery
- Comcast
- Roku
- Google
- Amazon
- Microsoft

### 별칭

- SK Broadband
- SKB
- SK 브로드밴드
- Broadband
- IPTV
- OTT
- Streaming
- Media
- 방송
- 통신
- B tv

## 3. 현재 구현 상태

- `profile.json`: 라우팅용 alias, keyword, market_keyword 정리 완료
- `sources/registry/sk_broadband/sources.json`: 공식·시장분석·경쟁사·사용자반응 Source 등록
- `adapter/collector`: Firecrawl 검색 수집 + KOFIC PDF 다운로드/parse 지원
- `adapter/processor`: 공백 정리, boilerplate 제거, 중복 제거
- `adapter/validator`: 출처·URL·본문 길이 기준 검증
- `adapter/analyzer`: SK Broadband 전용 prompt + Structured JSON 분석
- `adapter/reporter`: 공통 리포팅 단계에 넘길 수 있는 report payload 생성

분석 결과는 공통 계약인 `DocumentAnalysis`를 따른다. 모든 섹터가 동일하게 `summary`, `key_points`, `business_impact`, `risk`, `opportunity`, `recommended_actions`, `monitoring_indicators`, `evidence`, `action_level`, `analysis_confidence`를 사용한다.

## 4. 주요 Source

현재 실행용 Source Registry는 크롤링 부담과 분석 목적을 고려해 **섹터 전용 6개 Source**로 제한한다. 공통 Source인 네이버 뉴스 1개는 `sources/registry/common/`에서 자동 병합되므로, 실제 SourcePlan 기준으로는 **최대 7개 Source**가 사용된다.

| Source | role | reliability_tier | 목적 |
|---|---|---|---|
| SK브로드밴드 뉴스룸 | official | official | 공식 서비스·제휴·사업 발표 |
| KT 뉴스룸 | competitor_official | official | 경쟁사 공식 발표 비교 |
| KOCCA | market_analysis | official | 콘텐츠산업 시장동향·통계 |
| KOFIC | market_analysis | official | 영화산업 결산·콘텐츠 소비 흐름 |
| 전자신문(통신) | search | analyst_media | 통신·미디어 산업 뉴스 보완 |
| 왓챠피디아 | user_sentiment | user_generated | 콘텐츠 사용자 반응 보조 신호 |
| Naver News | search | common | 공통 뉴스 보완 |

URL, 유형, role, content_type, 활용 목적은 [SK Broadband Source Registry](../../sources/registry/sk_broadband/README.md)를 참고한다.

### 향후 검토 Source

기존 후보였던 방송통신위원회(KCC), 정보통신정책연구원(KISDI)은 정책·규제·통신시장 분석에 의미가 있으므로 후보로 보존한다. 다만 현재 `sources.json`에는 등록하지 않았고, 팀 회의에서 실제 수집 범위가 확정되면 추가 여부를 결정한다.

## 5. 분석 시 주의사항

### 자주 혼동되는 개념

- IPTV ≠ OTT
- Broadband ≠ Mobile
- AI 활용 ≠ AI 개발
- 사용자 반응 Source ≠ 공식 시장 통계
- 영화·콘텐츠 소비 흐름 ≠ SK브로드밴드 직접 실적

### 주의 이슈

- 개인정보
- 저작권
- AI 콘텐츠 규제
- 방송 규제
- 플랫폼 독점
- 망 사용료(Network Fee)
- AI 생성 콘텐츠의 신뢰성
- 경쟁사 발표의 홍보성
- 사용자 리뷰 데이터의 대표성 한계

## 6. 실제 질문 예시

### 시장 현황

- 국내 IPTV 시장은 어떻게 변화하고 있는가?
- OTT 시장 성장률은?
- FAST 시장 전망은?
- AI 기반 미디어 시장 규모는?
- B tv가 집중해서 봐야 할 미디어 플랫폼 변화는?

### 경쟁사

- Netflix의 AI 전략은?
- Disney+의 차별화 전략은?
- KT와 SK브로드밴드의 IPTV 경쟁력 비교
- YouTube Premium 성장 전략은?
- KT Genie TV의 최근 전략 변화는?

### 리스크

- 망 사용료 이슈가 미디어 산업에 미치는 영향
- AI 저작권 규제
- 개인정보 보호 강화 영향
- OTT 가입자 감소
- 콘텐츠 확보 비용 증가

### 미래 기회

- AI 추천 서비스
- AI Agent 기반 IPTV
- Hyper-personalization
- AI 광고
- Edge AI 기반 미디어
- Interactive Media
- B2B 미디어·네트워크 결합 서비스

## 7. 중요도 판단 기준

| High | Medium | Low |
|---|---|---|
| 시장 구조 변화 | 신기술 도입 사례 | 단순 기업 홍보 |
| 신규 규제 | 신규 서비스 출시 | 이벤트 |
| 글로벌 Big Tech 전략 | 투자 동향 | 일회성 마케팅 |
| AI 적용 사례 | 콘텐츠 전략 변화 | 지역 행사 |
| 주요 기업 실적 | 사용자 반응 변화 | 단기 프로모션 |
| 산업 패러다임 변화 | 제휴·파트너십 | 단순 제품 소개 |

## 8. Risk / Opportunity / Impact / Action 관점

분석은 단순 요약으로 끝나지 않고 다음 관점이 `key_points`와 전략 필드에 드러나야 한다.

- **Risk**: 가입자 이탈, 콘텐츠 비용, 규제, 경쟁 심화, 플랫폼 종속
- **Opportunity**: AI 추천, FAST, CTV 광고, B2B ICT, 데이터 기반 개인화
- **Business Impact**: 매출, ARPU, 가입자 성장, 비용 구조, 고객 접점, 네트워크 투자
- **Action**: Monitor, Review, Prepare, Act 중 하나의 대응 수준
- **Evidence**: 기사·공식자료·보고서에서 확인 가능한 근거

## 9. 다른 Sector와 중복되는 부분

| 질문 | 처리 Sector |
|---|---|
| HBM 시장 전망 | SK Hynix / Semiconductor |
| AI 반도체 개발 | SK Hynix / Semiconductor |
| 생성형 AI 산업 전체 | 질문 맥락에 따라 라우팅 |
| AI를 활용한 IPTV 추천 | SK Broadband |
| OTT 시장 분석 | SK Broadband |
| 통신 정책 | SK Broadband 또는 SK Telecom |
| 미디어 산업 AI 활용 | SK Broadband |
| AI 서버 인프라 | SK Hynix 또는 SK Telecom |
| 데이터센터 전력 | 질문 맥락에 따라 라우팅 |
| AI 기반 광고 시장 | SK Planet 또는 SK Broadband |
| 이커머스 개인화 추천 | SK Planet |

- SK하이닉스 → 반도체·AI 하드웨어 산업
- SK브로드밴드 → 미디어·통신·네트워크 산업
- SK플래닛 → 데이터 플랫폼·커머스·디지털 마케팅 산업
- SK텔레콤 → 통신·AI·네트워크 인프라 산업
- SK이노베이션 → 에너지·배터리·소재 산업

## 10. 대상별 강조 포인트

| 임원 | 실무진 | 외부인 | 경영진 |
|---|---|---|---|
| 시장 변화 | 기술 적용 사례 | 산업 개요 | 사업 리스크 |
| 경쟁사 전략 | 서비스 개선 방안 | 시장 규모 | 투자 방향 |
| 신규 사업 기회 | 운영 이슈 | 주요 기업 | 수익성 |
| 투자 우선순위 | AI 활용 방법 | 핵심 트렌드 | 전략적 의사결정 |
| 핵심 KPI | 세부 데이터 | 용어 설명 | 중장기 성장 기회 |

## 11. 운영 원칙

- 사용자가 섹터를 직접 선택하지 않아도 라우터가 질문을 기반으로 섹터를 판단한다.
- Source 수를 무작정 늘리지 않고 목적별 대표 Source를 유지한다.
- 공식 자료, 시장분석 자료, 뉴스, 사용자 반응의 역할을 구분한다.
- AI 분석 결과에는 추측보다 근거 기반 판단을 우선한다.
- Dashboard와 Report는 향후 report purpose에 따라 동적으로 구성될 수 있어야 한다.
