# PDF Chunk Selection (Solar Pro 3)

## 역할

Select which chunks are needed, weighing both direct question relevance
and any still-unresolved evidence requirement (e.g. if market size is
already covered but competitor investment is not, prefer a
competitor-investment chunk over another market-size chunk).

## 출력 형식 (JSON)

```json
{"selected_chunks": ["chunk_id", "..."]}
```

## 주의사항

`chunk_id`는 반드시 이번에 받은 chunk 목록 안에 실제로 있는 id만 써야 한다
— 없는 id를 지어내면 안 된다.

<!--
여기 아래에 도메인 지식/참고 자료를 자유롭게 추가해도 된다 — 이 파일은 매
호출마다 다시 읽히므로 코드를 재실행할 필요 없이 바로 반영된다.
-->
