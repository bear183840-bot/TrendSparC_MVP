# SK Planet sector

Status: `active`.

SK플래닛의 OK캐쉬백·Syrup, 포인트/리워드, 데이터 마케팅, Target Intelligence,
Ad-Tech, 모바일 커머스, 마이데이터와 Web3 로열티 생태계를 분석하는 섹터입니다.

## 라우팅

실제 alias·keyword는 `profile.json`이 기준입니다. 대표 신호는 SK플래닛,
OK캐쉬백, Syrup/시럽, 데이터 마케팅, 포인트·리워드, CDP, Ad-Tech, O2O,
마이데이터와 Web3입니다.

## 현재 구현

- `profile.json`: `active`
- Source Registry: 섹터 전용 16개 + 공통 소스
- Collector / Processor / Validator / Analyzer: 실제 구현 연결
- Analyzer: 구조화 JSON, 표·비교 완전성, 상대지표와 명시적 정성 등급 추출 규칙 적용

소스 목록과 역할은
[SK Planet Source Registry](../../sources/registry/sk_planet/README.md)를 참고합니다.
실제 URL과 메타데이터의 단일 기준은 `sources/registry/sk_planet/sources.json`입니다.

## 운영 주의

- OK캐쉬백과 Syrup 같은 브랜드/제품명을 일반 조직이나 기술 엔터티로 잘못 분류하지
  않습니다.
- 앱 이용률·광고 도달률·포인트 거래액·회원 수는 측정 대상과 분모가 다르면 분리합니다.
- 사용자 반응은 대표성 한계가 있으므로 공식 통계처럼 사용하지 않습니다.
- API·모델 설정은 `.env.example`을 따르며 실제 키는 저장소에 기록하지 않습니다.
