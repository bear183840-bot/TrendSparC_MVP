# SK Telecom sector

Status: `active`.

SK텔레콤의 5G/6G 이동통신, 에이닷/A.X, AI 데이터센터, 텔코 AI, 요금제·알뜰폰,
네트워크 정책과 국내외 통신사 전략을 분석하는 섹터입니다.

## 라우팅

실제 alias·keyword는 `profile.json`이 기준입니다. 대표 신호는 SK텔레콤/SKT,
5G·6G, 에이닷, A.X, AI 데이터센터, 피지컬 AI, UAM, 알뜰폰, 요금제와 T멤버십입니다.
IPTV·OTT·B tv 중심 질문은 `sk_broadband`로 분리합니다.

## 현재 구현

- `profile.json`: `active`
- Source Registry: 섹터 전용 13개 + 공통 소스
- Collector / Processor / Validator / Analyzer: 실제 구현 연결
- Analyzer: 구조화 JSON, 표·비교 완전성, 상대지표와 명시적 정성 등급 추출 규칙 적용

소스 목록과 역할은
[SK Telecom Source Registry](../../sources/registry/sk_telecom/README.md)를 참고합니다.
실제 URL과 메타데이터의 단일 기준은 `sources/registry/sk_telecom/sources.json`입니다.

## 운영 주의

- 이동통신 가입자·ARPU와 IPTV·초고속인터넷 가입자를 같은 지표로 합치지 않습니다.
- 경쟁사 공식 발표, 정부 정책, 시장분석과 일반 뉴스를 역할별로 구분합니다.
- 상대지표에서 원문에 없는 기준값을 역산하지 않습니다.
- API·모델 설정은 `.env.example`을 따르며 실제 키는 저장소에 기록하지 않습니다.
