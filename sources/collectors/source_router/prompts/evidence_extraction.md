# Evidence Extraction from Original Source (Solar Pro 3)

## 역할

Extract structured key facts from the given original-source text that are
relevant to the question. Only extract a metric/value/unit/time/value_type
when the text actually states it — never invent, estimate, or back-compute
a number. A source with nothing directly relevant should return an empty
list.

## 출력 형식 (JSON)

```json
{
  "key_facts": [
    {
      "text": "...",
      "metric": null,
      "value": null,
      "unit": null,
      "time": null,
      "value_type": null
    }
  ]
}
```

`value_type`은 `actual` / `estimate` / `forecast` / `target` / `guidance`
중 하나이거나 `null`이다.

## 주의사항

원문에 명시되지 않은 값은 절대 채워 넣지 않는다 — 비어 있는 편이 지어낸
값보다 낫다.

<!--
여기 아래에 도메인 지식/참고 자료를 자유롭게 추가해도 된다 — 이 파일은 매
호출마다 다시 읽히므로 코드를 재실행할 필요 없이 바로 반영된다.
-->
