# General sector

Status: `template_only`.

`general`은 사용자의 질문에서 특정 SK 계열사나 사업 섹터가 명확히 잡히지 않을 때 사용하는 fallback 섹터입니다.

## 역할

- 섹터 미지정 질문을 안전하게 받는다.
- 공통 Source인 네이버 뉴스 등 범용 Source를 사용할 수 있다.
- 실제 계열사별 분석이 필요한 경우에는 `sk_hynix`, `sk_planet`, `sk_telecom`, `sk_innovation`, `sk_broadband` 등 명확한 섹터로 라우팅하는 것이 우선이다.

## 아직 안 된 것

`adapter/collector`부터 `adapter/analyzer`까지 실제 수집·분석 로직은 구현하지 않았다. 호출되면 명시적인 `PipelineStageError`를 발생시켜 어느 단계에서 멈췄는지 trace로 확인할 수 있게 한다.
