# SK Broadband sector

Status: `template_only`.

SK Broadband 섹터의 범위, 라우팅 용어, 분석 기준과 대상별 강조
포인트를 정의한다. 실제 수집·분석 adapter는 아직 구현하지 않는다.

## 1. Sector 범위

### 포함하는 내용

- IPTV 및 유료방송 시장
- OTT 및 스트리밍 서비스
- 미디어 플랫폼 산업
- 콘텐츠 유통 및 제작 생태계
- AI 기반 미디어 서비스
- 방송·통신 융합 서비스
- 초고속 인터넷(Broadband)
- 네트워크 인프라
- CDN(Content Delivery Network)
- Edge Computing
- AI Recommendation
- Personalized Content
- FAST(Free Ad-supported Streaming TV)
- 디지털 광고(CTV Advertising 포함)
- 미디어 관련 정책 및 규제
- 방송통신위원회·과기정통부 정책
- AI 기반 고객경험(CX)
- 미디어 산업의 생성형 AI 활용

### 포함하지 않는 내용

- 반도체 제조 기술
- AI 모델 자체 연구(LLM 개발)
- 일반 제조업
- 금융 산업
- 바이오 산업
- 자동차 산업
- 게임 산업(미디어 관점 제외)
- 스마트팩토리
- 메모리 반도체 시장
- AI 칩 개발

## 2. 핵심 키워드 및 용어

### 주요 키워드

- IPTV
- OTT
- Streaming
- FAST
- CTV
- CDN
- Broadband
- Fiber Network
- AI Media
- Personalized Recommendation
- Content Discovery
- AI Search
- Video AI
- AI Agent
- Hyper-personalization
- Edge AI
- Connected TV
- Digital Media
- Media Platform
- Subscription
- Ad-supported Streaming

### 영문 용어

| 영문 용어 | 의미 |
|---|---|
| Broadband | 초고속 인터넷 |
| IPTV | 인터넷TV |
| OTT | 온라인동영상서비스 |
| FAST | 광고기반 무료스트리밍 |
| Connected TV (CTV) | 연결형 TV |
| CDN | 콘텐츠전송망 |
| Generative AI | 생성형 AI |
| Personalization | 개인화 추천 |
| Media Platform | 미디어 플랫폼 |
| Streaming | 스트리밍 |

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

## 3. 주요 Source

현재 실행용 Source Registry는 크롤링 부담과 분석 목적을 고려해 **섹터 전용 5개 Source**로 제한한다.
공통 Source인 네이버 뉴스 1개는 `sources/registry/common/`에서 자동 병합되므로, 실제 SourcePlan 기준으로는 **최대 6개 Source**가 사용된다.

### 현재 등록 Source

- SK브로드밴드 뉴스룸
- KT 뉴스룸 (경쟁사 공식 자료)
- 한국콘텐츠진흥원(KOCCA)
- 전자신문 (통신)
- 왓챠피디아
- 공통 Source: 네이버 뉴스

URL, 유형, role, content_type, 활용 목적은
[SK Broadband Source Registry](../../sources/registry/sk_broadband/README.md)를
참고한다.

### 향후 검토 Source

기존 후보였던 방송통신위원회(KCC), 정보통신정책연구원(KISDI)은 정책·규제·통신시장 분석에 의미가 있으므로 후보로 보존한다. 다만 현재 `sources.json`에는 등록하지 않았고, 팀 회의에서 실제 수집 범위가 확정되면 추가 여부를 결정한다.

## 4. 분석 시 주의사항

### 자주 혼동되는 개념

- IPTV ≠ OTT
- Broadband ≠ Mobile
- AI 활용 ≠ AI 개발

### 주의 이슈

- 개인정보
- 저작권
- AI 콘텐츠 규제
- 방송 규제
- 플랫폼 독점
- 망 사용료(Network Fee)
- AI 생성 콘텐츠의 신뢰성

## 5. 실제 질문 예시

### 시장 현황

- 국내 IPTV 시장은 어떻게 변화하고 있는가?
- OTT 시장 성장률은?
- FAST 시장 전망은?
- AI 기반 미디어 시장 규모는?

### 경쟁사

- Netflix의 AI 전략은?
- Disney+의 차별화 전략은?
- KT와 SK브로드밴드의 IPTV 경쟁력 비교
- YouTube Premium 성장 전략은?

### 리스크

- 망 사용료 이슈가 미디어 산업에 미치는 영향
- AI 저작권 규제
- 개인정보 보호 강화 영향
- OTT 가입자 감소

### 미래 기회

- AI 추천 서비스
- AI Agent 기반 IPTV
- Hyper-personalization
- AI 광고
- Edge AI 기반 미디어
- Interactive Media

## 6. 중요도 판단 기준

| High | Medium | Low |
|---|---|---|
| 시장 구조 변화 | 신기술 도입 사례 | 단순 기업 홍보 |
| 신규 규제 | 신규 서비스 출시 | 이벤트 |
| 글로벌 Big Tech 전략 | 투자 동향 | 일회성 마케팅 |
| AI 적용 사례 | 콘텐츠 전략 변화 | 지역 행사 |
| 주요 기업 실적 |  | 단기 프로모션 |
| 산업 패러다임 변화 |  |  |

## 7. 다른 Sector와 중복되는 부분(혼동 위험)

| 질문 | 처리 Sector |
|---|---|
| HBM 시장 전망 | 반도체 |
| AI 반도체 개발 | 반도체 |
| LLM 모델 성능 비교 | 미정 |
| 생성형 AI 산업 전체 | 미정 |
| AI를 활용한 IPTV 추천 | 미디어 |
| OTT 시장 분석 | 미디어 |
| 통신 정책 | 미디어 |
| 미디어 산업 AI 활용 | 미디어 |
| AI 서버 인프라 | 반도체 |
| 데이터센터 전력 | 미정 또는 반도체(범위에 따라) |
| AI 기반 광고 시장 | 유통 |
| 이커머스 개인화 추천 | 유통 |

- SK하이닉스 → 반도체·AI 하드웨어 산업
- SK브로드밴드 → 미디어·통신·네트워크 산업
- SK플래닛 → 데이터 플랫폼·커머스·디지털 마케팅 산업

## 8. 대상별 강조 포인트

| 임원 | 실무진 | 외부인 | 경영진 |
|---|---|---|---|
| 시장 변화 | 기술 적용 사례 | 산업 개요 | 사업 리스크 |
| 경쟁사 전략 | 서비스 개선 방안 | 시장 규모 | 투자 방향 |
| 신규 사업 기회 | 운영 이슈 | 주요 기업 | 수익성 |
| 투자 우선순위 | AI 활용 방법 | 핵심 트렌드 | 전략적 의사결정 |
| 핵심 KPI | 세부 데이터 | 용어 설명 | 중장기 성장 기회 |

## 아직 안 된 것

`adapter/collector`부터 `adapter/analyzer`까지 실제 수집·분석 로직은
아직 구현되지 않았다. 가짜 데이터를 추가하지 않으며, 미구현 함수는
명시적인 `PipelineStageError`를 발생시킨다.
