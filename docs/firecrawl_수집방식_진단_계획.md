# Firecrawl 수집 방식(search vs crawl) 진단 — 실행 과정

> 상태: 계획 단계, 아직 실행 안 함

## 0단계 — 검색어 준비 (Firecrawl 호출 없음)

대표 질문 8개를 실제 프로덕션 경로인 `core/entity/ai_based.py::extract_entities_ai()`에 통과시켜
`EntityExtractionResult`를 얻고, `core/entity/search_terms.py::build_search_terms()`로 실제
검색어를 뽑는다. 소스의 `topics` 필드는 실제 프로덕션에서 검색어로 안 쓰이므로 이번 진단에도
쓰지 않는다.

**엔티티 추출 키 처리 — 기존 코드는 전혀 안 건드림.** `extract_entities_ai()`는
`os.environ["TRENDSPARC_ENTITY_AI_API_KEY"]`를 고정 조회하는 구조라(`core/entity/ai_based.py`
자체는 수정하지 않음), 진단 스크립트가 시작할 때 별도의 진단 전용 키
(`TRENDSPARC_DIAGNOSTIC_ENTITY_AI_API_KEY`, `.env.example`에 placeholder만 추가)를 읽어서
`os.environ["TRENDSPARC_ENTITY_AI_API_KEY"]`에 프로세스 내에서만 임시로 주입한 뒤 호출한다.
이 키를 안 채워도 `extract_entities_ai()`가 자체적으로 무료 rule-based 결과로 조용히
폴백하므로 스크립트는 그대로 동작한다(0단계만 rule-based 품질이 됨). 채우면 질문 8개 ×
1회(gpt-4o-mini) 정도의 작은 OpenAI 비용이 발생한다.

| # | 질문 | 겨냥 role | perspective | intent |
|---|---|---|---|---|
| 1 | SK브로드밴드 IPTV 신규 서비스 현황이 궁금해 | `official` (서비스 뉴스) | company_update | current_status |
| 2 | 국내 OTT 시장 경쟁 구도가 어떻게 되고 있어? | `market_analysis`/`search` | market_landscape | current_status |
| 3 | KT, LG유플러스와 비교했을 때 SK브로드밴드의 경쟁력은? | `competitor_official` (국내) | competitor_comparison | current_status |
| 4 | Netflix, Disney+ 같은 글로벌 OTT 대비 SK브로드밴드의 대응 전략은? | `competitor_official` (글로벌) | competitor_comparison | issue_response |
| 5 | 망 사용료 관련 규제 이슈에 어떻게 대응해야 해? | `regulatory_official` | regulatory_policy | issue_response |
| 6 | 국내 콘텐츠 시장 트렌드는 향후 어떻게 변할까? | `market_analysis` (콘텐츠 소비 흐름) | market_landscape | future_business |
| 7 | SK브로드밴드 IPTV 사용자 만족도가 최근 왜 떨어지고 있는지 궁금해 | `user_sentiment` | company_update | root_cause |
| 8 | SK브로드밴드 최근 매출과 영업이익 실적은 어때? | `official` (IR/실적) | company_update | current_status |

각 소스는 자기 role에 매칭되는 질문의 검색어를 쓴다. `official` role 소스는 1번·8번 검색어를 둘 다 시도한다.

## 1단계 — 소스별 Firecrawl 호출

- `sources/registry/sk_broadband/sources.json` 로드 (KOFIC PDF 소스는 별도 검증된 방식이라 스킵)
- 소스마다 동일 조건(`limit=3`)으로:
  - **search**: 0단계 검색어로 `client.search(query, include_domains=[도메인], limit=3)`
  - **crawl**: 등록 URL부터 `client.crawl(url, limit=3, max_discovery_depth=2, timeout=90)`
  - 문서 수 / 평균 본문 길이 / 유효 문서 수(`_MIN_CONTENT_LENGTH=250` 기준) 기록
  - 둘 다 유효 문서 0건이면 **extract** 1회 추가 시도
- API 실패는 삼키지 않고 `{"status": "error", "error_message": "..."}`로 그대로 기록. 같은 에러가
  연속 2회 이상 뜨면(크레딧 소진 등) 조기 중단하고 지금까지 결과만 저장.

## 2단계 — 샘플에 제목 + URL + 한줄 요약 기록

숫자만으로는 판단이 어려우므로, 소스·방식별 샘플 문서 최대 2~3개에 대해:

- 제목
- URL
- 한줄 요약 — 추가 API 호출 없이, 스크랩된 markdown에서 헤더(`#`)·이미지 문법 제거 후
  첫 문단 앞부분 약 100~150자를 잘라서 생성

## 3단계 — 결과물 저장

콘솔에 실시간 진행 상황 출력:

```text
[1/13] SK브로드밴드 뉴스룸 / search: 3건, 유효 3건 / crawl: 2건, 유효 2건 / → 추천: search
```

`scratchpad/collection_method_diagnosis_sk_broadband.json`에 소스별 결과 저장:

```json
{
  "source_name": "...",
  "source_url": "...",
  "search": {
    "query_used": "...", "status": "ok",
    "document_count": 3, "valid_document_count": 3, "avg_content_length": 1200,
    "samples": [{"title": "...", "url": "...", "one_line_summary": "..."}],
    "error_message": null
  },
  "crawl": { "...": "동일 구조" },
  "extract": null,
  "recommended_method": "search"
}
```

`recommended_method`는 유효 문서 수 우선, 동률이면 평균 본문 길이로 판단하는 단순 규칙 — 최종
판단은 사람이 리포트를 보고 확정. 스크립트는 registry를 자동으로 덮어쓰지 않는다.

## 4단계 — 사람이 리포트 검토 후 registry 반영

1. 소스별 승자 방식과 샘플(제목·한줄 요약)이 실제로 관련 있는지 확인
2. `sources.json`의 `collection_method` 확정된 방식으로 수동 갱신
3. `reliability_reason`에 비교 근거 기록, `README.md`에도 반영
4. JSON 유효성 확인 + `pytest tests/test_source_registry_quality.py
   tests/test_sk_broadband_adapter.py tests/test_source_planner.py -q`
