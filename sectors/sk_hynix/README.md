# SK hynix sector

Status: `active`.

SK하이닉스의 DRAM·NAND·HBM 시장, 투자·CAPEX, 실적, 공급망, 고객사·경쟁사와
반도체 정책·규제를 분석하는 섹터입니다.

## 라우팅

실제 alias·keyword·market keyword는 `profile.json`이 기준입니다. 대표 신호는
SK hynix/SK하이닉스, HBM, DRAM, NAND, 메모리, NVIDIA, Micron, 삼성전자,
CAPEX와 반도체 공급망입니다. 통신·IPTV 질문은 `sk_broadband` 또는 `sk_telecom`으로
분리합니다.

## 현재 구현

- `profile.json`: `active`
- Source Registry: 섹터 전용 14개 + 공통 소스
- Collector / Processor / Validator / Analyzer: 실제 구현 연결
- Analyzer: 구조화 JSON, 표·비교 완전성, 상대지표(YoY/CAGR/증감률), 명시적 정성
  등급 추출 규칙 적용
- 명시 alias: Samsung Electronics/삼성전자, SK hynix/SK하이닉스,
  Micron Technology/마이크론
- HBM 시장 규모·매출처럼 동일하다고 검토된 지표 표현만 합치고, 지역 범위·출하량·
  다른 제품 지표는 분리

소스 목록·역할·접근 검증 내역은
[SK hynix Source Registry](../../sources/registry/sk_hynix/README.md)를 참고합니다.
실제 URL과 메타데이터의 단일 기준은 `sources/registry/sk_hynix/sources.json`입니다.

## 운영 주의

- 원문에 없는 절대 시장값을 성장률이나 배수에서 역산하지 않습니다.
- global/Korea, revenue/shipments, HBM/DRAM처럼 범위나 측정 정의가 다르면 같은
  시계열로 합치지 않습니다.
- 경쟁사·고객사 공식 발표는 각 회사 관점의 자료이므로 독립 출처와 교차 확인합니다.
- API·모델 설정은 `.env.example`을 따르며 실제 키는 저장소에 기록하지 않습니다.
