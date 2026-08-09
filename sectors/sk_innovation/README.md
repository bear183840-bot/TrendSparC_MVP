# SK Innovation sector

Status: `active`.

SK이노베이션과 SK온·SK에너지·SK지오센트릭·SK엔무브를 중심으로 배터리, 정유,
석유화학, 윤활유, ESS와 친환경 에너지 밸류체인을 분석하는 섹터입니다.

## 라우팅

실제 alias·keyword는 `profile.json`이 기준입니다. 대표 신호는 SK이노베이션,
SK온, 배터리·이차전지, 정제마진, 석유화학, ESS, 친환경에너지와 공급망입니다.

## 현재 구현

- `profile.json`: `active`
- Source Registry: 섹터 전용 12개 + 공통 소스
- Collector / Processor / Validator / Analyzer: 실제 구현 연결
- Analyzer: 구조화 JSON, 표·비교 완전성, 상대지표와 명시적 정성 등급 추출 규칙 적용

소스 목록과 역할은
[SK Innovation Source Registry](../../sources/registry/sk_innovation/README.md)를
참고합니다. 실제 URL과 메타데이터의 단일 기준은
`sources/registry/sk_innovation/sources.json`입니다.

## 운영 주의

- 배터리·정유·석유화학은 단위와 시장 정의가 다르므로 같은 시계열로 합치지 않습니다.
- 원자재 가격·원가 비중·점유율은 분모와 지역·기간이 일치할 때만 비교합니다.
- 공식 발표와 시장분석·규제·일반 뉴스를 역할별로 교차 확인합니다.
- API·모델 설정은 `.env.example`을 따르며 실제 키는 저장소에 기록하지 않습니다.
