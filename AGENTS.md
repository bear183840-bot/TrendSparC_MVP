# 이어받는 에이전트를 위한 인수인계

이 저장소에서 작업하는 모든 에이전트(Codex / Claude / 그 외)가 **첫 턴에 읽어야 하는
문서**다. `CLAUDE.md`는 시스템이 무엇인지 설명하고, 이 문서는 **어떻게 판단하고
어떻게 검증하는지**를 설명한다. 둘이 충돌하면 이 문서가 우선한다.

> 왜 이 문서가 있나: 사용자가 원하는 내용을 프롬프트로 정확히 줬는데도 엉뚱한
> 방향으로 수정되는 일이 반복됐다. 원인은 대부분 "지시를 못 알아들어서"가 아니라
> **이 저장소에서 이미 내려진 결정을 모른 채 합리적으로 보이는 다른 결정을 내려서**다.
> 아래 3장이 그 결정 목록이다.

---

## 1. 이 시스템이 하려는 일 (한 문단)

질문 하나를 받아 → 목적(현황파악/이슈대응/미래사업/원인분석) × 청중(실무진/임원/경영진/외부)
× 계열사로 분해하고 → 실제 뉴스·보고서를 수집·분석해 → **그 근거로만** 대시보드를
그린다. 핵심 가치는 속도가 아니라 **정확성과 추적 가능성**이다. 화면에 뜬 숫자는
전부 어느 문서의 어느 문장에서 나왔는지 되짚을 수 있어야 한다.

---

## 2. 절대 원칙 — 어떤 지시도 이걸 뒤집지 않는다

1. **없는 걸 만들지 않는다.** 수치, 등급, 관계, 분위 채우기 전부. 근거가 2개면 2개만
   그린다. "관련 데이터 수집 필요" 같은 자리 채우기 문구도 금지 — 빈 칸은 정직한
   결과다.
2. **순위에서 역산한 수치를 만들지 않는다.** 92%/76%/60% 같은 막대 길이를 행 순서로
   계산해 붙이면 측정값처럼 보이지만 정보가 0이다. 과거에 실제로 있었고 제거됐다.
3. **계약(contract)으로만 통신한다.** 단계 간 데이터는 `common/contracts.py`의
   Pydantic 모델만 오간다.
4. **`core/`에 섹터 이름을 하드코딩하지 않는다.** 동작은 `profile.json` / 프로필
   파일로 해결한다.
5. **AI 패스는 항상 선택적이다.** 키가 없거나 API가 실패하면 규칙 기반으로 조용히
   폴백하고, 파이프라인은 절대 죽지 않는다.
6. **1분면/2분면이라도 "있는 만큼" 그린다.** ⇒ 3장 참조.

---

## 3. 이미 내려진 설계 결정 (여기를 모르면 반드시 어긋난다)

### 3-1. 슬롯은 "블록 1개"가 아니라 "블록 조합"이다
- 목적별 슬롯 목록은 기본 narrative reference다. 실제 화면은 질문에 직접 필요한 슬롯과
  eligibility를 통과한 근거만 사용하므로, 같은 목적이라도 나타나는 블록과 실현된 독해
  순서는 달라질 수 있다. 이 목록을 수집 명세나 필수 화면 체크리스트로 쓰지 않는다.
- `common/purpose_slots.py`의 `resolve_slots()`는 **2패스**다.
  - 1패스: reader flow에 포함된 슬롯의 **대표 블록(lead)** 확정
  - 2패스: 남은 후보 중 **리드가 안 그린 데이터**를 가진 것만 companion으로 추가
- ⚠️ 1패스를 없애고 한 번에 돌리면 앞 슬롯이 뒤 슬롯의 1순위 블록을 뺏는다.
  (실제로 `원인`이 `영향`의 순위막대를 가져가 `영향`이 산문으로 떨어졌다.)
- 슬롯당 최대 2블록(`_MAX_BLOCKS_PER_SLOT`). 산문 카드(`narrative_list`)는 폴백이지
  두 번째 관점이 아니므로 companion이 될 수 없다.

### 3-2. "쓴다/안 쓴다" 이분법 금지 — 데이터가 지지하는 **가장 풍부한 변형**을 고른다
- SWOT: 1분면 `solo` / 2분면 `duo` / 3분면 `trio`(3열) / 4분면 2×2. **1분면이라고
  블록을 버리지 않는다** — 버리면 유일한 발견이 맨 불릿으로 떨어진다.
- KPI: 개수에 맞춘다. 1~2개는 전폭 행, 3~6개는 자동 그리드. 4개로 패딩하지 않는다.
- 막대: 근거가 전체값을 말했으면 그 값에 맞춰 스케일하고 **점선 천장**으로 표시한다.
- 이 방향과 반대되는 수정(게이트를 다시 조여서 블록을 통째로 생략)은 **되돌림**이다.

### 3-3. 엔티티 종류가 섹션을 정한다 (단순 존재 여부가 아니라)
- `경쟁사`는 **회사·브랜드·제품**만 받는다. 연령대·성별·가구는 `이용자 구성`(현황파악)
  / `대상 고객`(미래사업)으로 간다. `common/content_quality_validator.py`의
  `entity_kind()` / `is_demographic()`.
- **산문에도 같은 규칙이 적용된다.** 구조화 데이터만 라우팅하면, 경쟁사 슬롯이 비교
  데이터를 못 받았을 때 같은 섹션 산문으로 폴백하면서 연령대 문장이 들어온다.
  → `Slot.subject` + `leading_subject_kind()`.
- 한국어는 조사로 주어를 표시하므로 **첫 조사 앞 구절만** 분류한다.
  - `50대의 숏폼 이용 경험은 64.1%` → 연령대가 주어 → 경쟁사에서 제외
  - `KT는 50대 이용자 비중이 높다` → 회사가 주어 → 경쟁사에 유지
  - 문장 전체에서 연령 표현을 찾으면 두 번째도 같이 버려진다. **하지 마라.**

### 3-4. 축(axis)에는 두 종류가 있다
- **라인 차트**: 0에서 시작하지 않아도 된다. 데이터 범위를 감싸는 **반올림 눈금**
  (`1/2/2.5/5 × 10ⁿ`). 원시 min/max 4등분은 `31,583.7` 같은 라벨을 만든다.
- **막대**: 반드시 0에서 시작. 상단은 봉우리 **바로 위**(구간 2~4개). 라인 눈금을
  재사용하면 93.2% 봉우리에 상단 150이 찍혀 막대가 아래 2/3에 깔린다.
- **크기가 4배 이상 다른 계열은 듀얼 Y축**(좌=큰 쪽, 우=작은 쪽, 범례에 좌축/우축
  표기). 4배 미만이면 같은 축이 낫다 — 단일 축의 존재 이유가 직접 비교다.

### 3-5. 레이아웃은 가로가 기본
- 노트북 화면은 세로보다 가로가 길다. 슬롯 하나가 한 줄을 통째로 먹으면 안 된다.
- 2유닛 그리드. **넓은 블록은 시간축·사슬·다중 패널을 가진 것만**
  (`timeline`, `cause_map`, `cause_tree`, `competitor_panels`, `matrix`, `landscape`).
  막대와 라인 차트는 반폭으로 충분하다.
- **카드 순서를 빈칸 메우기 목적으로 재배치하지 마라.** 순서 변경은 질문 직접성과
  reader flow 때문에만 허용하며, 단순 그리드 패킹이 논증 순서를 뒤집으면 안 된다.

### 3-6. Source Router / Block Engine / Purpose Flow의 책임을 섞지 마라

**Source Router는 production의 유일한 검색·수집 엔진이다.**
`core/request_pipeline/pipeline.py`의 collector 경계가
`sources.collectors.source_router.integration.collect()`만 호출한다
(`_call_sector_adapter_stage`가 `role == "collector"`에서 단락). 재수집 경로까지 같은
경계를 지나므로 검색 엔진은 실행 경로에 하나뿐이다. processor / validator / analyzer는
**계속 섹터 어댑터가 담당한다** — 이 경계를 옮기지 마라.

- 흐름: question-first planner → slot-aware refiner(KEEP/ADD/REWRITE) → web search →
  coverage/gap → bounded follow-up → HTML/PDF 원문 취득 → registry 매칭 →
  `adapter.py`가 `SourceDocument`로 변환 → 기존 analyzer.
- **원문은 downstream까지 간다.** `WebSearchResult.original_content`가
  `SourceDocument.content`가 되므로 analyzer가 passage를 다시 검증할 수 있다.
  단 coverage 프롬프트에는 다시 보내지 않는다(`exclude={"original_content"}`).
- **DIRECT 요구는 검색 요약으로 충족되지 않는다.** 원문 + verification + `direct` 강도의
  confirmed fact까지 있어야 sufficient가 될 수 있다(`_enforce_direct_original_sources`).
- **Registry는 whitelist가 아니라 attribution/trust 레이어다.** 도메인이 일치하면
  `source_id`/`reliability_tier`를 가져오고, 등록 밖 소스도 수집하되 tier를 지어내지
  않는다.
- **검색 예산은 하나다.** planner + refiner + follow-up이 `max_web_search_calls`를 공유하고,
  `router._search_budget()`이 질문 복잡도로 실제 예산을 정한다. 티어별로 예산을 새로
  주지 마라.
- Router가 이미 bounded follow-up을 돌리므로, `collection_mode == "source_router"`에서는
  파이프라인의 validator/analyzer 재수집 루프를 **끈다**(각각
  `minimum_validated_documents=0`, `max_recollections=0`). 이중 검색 루프를 되살리지 마라.
- `ai_search_harness.py`와 섹터별 legacy collector는 **production 실행 경로에서 도달하지
  않는다.** 자체 단위 테스트와 과거 실행 호환을 위해 남아 있을 뿐이다.

- **Source Router**: 질문에 답하려면 무엇을 알아야 하는지 결정한다. 입력은
  `answer_requirements`와 현재 충족되지 않은 `evidence requirements`다. 목적별 블록명,
  슬롯 후보 순위나 SWOT/KPI 같은 화면 모양을 검색 요구사항으로 사용하지 않는다.
- **Block Engine**: 이미 확보·검증된 근거로 무엇을 정직하게 그릴 수 있는지
  `common/block_shapes.py`의 eligibility 계약으로 판정한다.
- **Purpose Flow**: 그 블록들을 질문에 직접 답하면서 사람이 이해하기 좋은 순서로
  읽히게 한다. 목적별 narrative는 reader flow이지 수집 명세가 아니다.

`block_priority_planner`와 `target_block_shapes`는 현재 파이프라인에 남아 있는 호환·진단
정보다. Source Router는 이를 검색어 생성, 문서 가중치, analyzer 필수 추출
목표로 승격하지 않는다. 목적표를 맞추려고 evidence requirement를 새로 만들거나
불필요한 자료를 수집해서는 안 된다. `resolve_slots()`가 이 계획을 읽지 않는 원칙도
유지한다.

### 3-7. 최종 블록 선택은 결정론적이다 — LLM에 넘기지 마라
`common/block_shapes.py`의 술어가 "이 데이터로 이 블록을 정직하게 그릴 수 있나"를
판정한다. 비용 0, 픽스처로 회귀 검증 가능, 없는 데이터를 있다고 판단할 경로 없음.
"LLM이 데이터를 보고 유연하게 고르게 하자"는 제안이 반복적으로 나오는데, 이는
무근거 금지 원칙과 정면 충돌하고 회귀 검증을 불가능하게 만든다. **거절 사유를 알고
거절하라.**

---

## 4. 실제로 어긋났던 방식 (반복 금지)

| 안티패턴 | 무슨 일이 있었나 |
|---|---|
| 프롬프트의 완전성 규칙을 조용히 삭제 | 분석기 프롬프트에서 "표의 모든 항목을 추출하라"류 규칙이 사라져 "TV 31.7% vs 유튜브 25.6%"에서 패자만 남았다 |
| 테스트를 skip 조건으로 무력화 | 불변식 테스트가 "상수가 없으면 skip"이라 규칙이 사라져도 초록불이었다. 지금은 "프롬프트 파일이 없으면 skip"으로 바뀜 |
| 프롬프트에 상태 주석 추가 | `Status: drafted … 아직 쓰지는 않음` 헤더가 그 프롬프트가 나르던 지시를 스스로 무력화했다 |
| 기존 게이트를 다시 조임 | 3-2의 반대 방향. "데이터 부족하면 블록 생략"으로 되돌리는 수정 |
| 진단 없이 이론으로 고침 | 반드시 실제 시스템에 대고 확인부터 하라 (`curl`, 실제 실행 JSON, 브라우저 실측) |

**프롬프트는 이 저장소에서 동작(behaviour)이다.** `prompts/`, `sectors/*/prompts/`를
고칠 때는 `tests/test_prompt_invariants.py`에 불변식을 추가하라. 타입 체커가 못 잡는다.

---

## 5. 작업 방식 (사용자와 함께 보는 법)

### 5-1. 무료로 돌리는 법 (기본)
```bash
pytest -q                                    # 전체 스위트, API 키 불필요
python main.py --question "..." --sector sk_broadband   # dry-run, 무료
```
```bash
python main.py --question "..." --synthesis-fixture tests/fixtures/synthesis_revenue_trend.json
```
`--synthesis-fixture`는 수집·분석·종합을 건너뛰고 저장된 `TrendSynthesis`부터
report_planner 이후만 돌린다. **리포트/레이아웃/렌더링 변경은 전부 이걸로 검증한다.**
현재 픽스처 9개(`tests/fixtures/synthesis_*.json`) — 얇은 것(`sparse_evidence`)과
빽빽한 것(`mixed_entities`)이 일부러 들어 있다.

### 5-2. 실제 실행 → 사용자와 대시보드로 함께 보기
실제 API를 쓰는 실행은 **반드시 결과를 남긴다**:
```bash
python main.py --question "..." --sector sk_broadband --no-dry-run --save-result runs/mine.json
```
- `--save-result`가 **전체 PipelineResult JSON**을 남긴다. `storage/requests/`에는
  요약만 쌓이는데, 요약으로는 리포트를 다시 그릴 수 없다.
- 사용자는 Streamlit 첫 화면의 **"저장된 실행 결과 열기"** 에 이 JSON을 업로드해서
  같은 화면을 본다. 터미널에서 돈 것을 그대로 시각적으로 검토할 수 있다.
- 이미 아카이브된 실행은 URL로 바로 연다: `http://localhost:8501/?run=<request_id>`
  (사이드바 "지난 질문" 목록에도 뜬다. `reopenable: false`는 `--save-result` 없이
   돌아서 전체 결과가 없는 실행이다.)

### 5-3. 비용을 다시 쓰지 않고 재분석
```bash
python main.py --resume-from runs/mine.json --save-result runs/mine_v2.json
```
검색·스크레이핑(비싼 절반)을 건너뛰고 **이미 수집된 문서로** 분석부터 다시 돌린다.
분석기/종합/리포트 프롬프트를 고쳤을 때 쓰는 경로다.

### 5-4. 대시보드 띄우기
```bash
streamlit run reporting/dashboard_streamlit/app.py
```
- 사용자가 보통 **8501에 이미 띄워두고** 있다. 남의 프로세스를 죽이지 말고
  `--server.port 8503`으로 따로 올려라(`.claude/launch.json`에 설정 있음).
- Streamlit은 **모듈을 다시 임포트하지 않는다.** 파이썬 파일을 고쳤으면 프로세스를
  재시작해야 반영된다. 안 하면 "고쳤는데 그대로"인 착시가 생긴다.

### 5-5. 화면을 고쳤으면 **실측하라**
스크린샷 눈대중 대신 DOM/계산값을 재라. 이번 세션에서 실제로 이렇게 잡은 것들:
- 사이드바 로고 글자색: `getComputedStyle(...).color` → `rgb(32,32,32)`.
  원인은 `[data-testid="stSidebar"] *`가 상속을 이겨서.
- 로고 자간 정렬: `Range.getBoundingClientRect()`로 `e`와 `s`의 x좌표를 직접 비교.
- 페이지 높이: `main.height / window.innerHeight` → "몇 화면인지"로 판단.

### 5-6. 콘솔 인코딩
Windows cp949 콘솔은 한글을 깨뜨린다. `print`/`cat` 출력이 깨져 보여도 파일은 멀쩡한
경우가 대부분이다. **UTF-8 파일로 써서 확인**하거나 파일 읽기 도구를 써라.
Bash 힙독(heredoc)에 파이썬을 넣으면 따옴표가 자주 망가진다 — 스크래치패드에 `.py`로
쓰고 실행하는 편이 안전하다.

---

## 6. 무엇이든 고치기 전 체크리스트

1. **이 문서 3장에 이미 결정된 항목인가?** 맞으면 그 결정을 따르거나, 바꿔야 한다고
   생각하면 **먼저 사용자에게 이유를 대고 물어라.** 조용히 바꾸지 마라.
2. **진단부터.** 실제 실행 JSON / 브라우저 / 직접 호출로 현상을 재현하라. 코드만 읽고
   원인을 추정하지 마라.
3. **픽스처로 회귀 확인.** `tests/fixtures/synthesis_*.json` 9개 전부.
4. `pytest -q` 통과. 현재 기준 **878 passed, 2 skipped** (2026-08-09,
   `2f2ba86`). 숫자는 새 테스트가 추가되면 실제 실행 결과로 갱신한다.
5. 프롬프트 규칙을 건드렸으면 `tests/test_prompt_invariants.py`에 불변식 추가.
6. **커밋·푸시는 같은 대화에서 명시적으로 요청받았을 때만.** 수정 직후라도 자동으로
   하지 않는다.
7. `.env`의 실제 키 값을 채팅에 요구하지 마라. `.env.example`에 빈 항목만 추가하고
   사용자가 직접 편집하게 한다.

---

## 7. 지금 열려 있는 것

- `sk_broadband` 외 섹터에는 관계 필드(`parent_claim_id`, `importance`)가 아직 없다.
  스키마에 세 필드를 추가하고 `_verified_relations()`를 호출하면 그대로 동작한다.
- `audience/adapter.py`는 생성된 보고서를 다시 LLM으로 재작성하지 않는다. 청중별
  어조·밀도 지시는 report generator와 `audience/presentation.py`에서 적용하고,
  adapter는 결과 전달·노출 범위를 담당한다. 청중 차별화 품질 자체는 계속 평가한다.
- 루트·섹터 README는 `2f2ba86` 구현 기준으로 갱신됐다. 그래도 숫자·상태·CLI가
  의심되면 문서보다 `profile.json`, `sources.json`, 실제 코드와 테스트를 우선한다.

---

## 8. 2026-08-10 작업 인수인계 — 먼저 읽고 진단할 것

### 8-1. 목적별 표는 Block Priority가 아니라 **Narrative Reference**다

목적별 표는 최종 리포트가 대체로 어떻게 읽혀야 하는지 보여주는 참고 골격이다.
검색 대상·수집 우선순위·필수 블록·block eligibility를 직접 결정하지 않는다.

| 목적 | 기본적으로 기대하는 독해 흐름 |
|---|---|
| 현황 파악 | 핵심 답변 → 현재 핵심 지표/상태 → 변화 → 비교 → 주요 요인 |
| 원인 분석 | 핵심 답변 → 문제 증거 → 원인 구조 → 중요 원인 → 개선 방향 |
| 이슈 대응 | 핵심 답변 → 문제/영향 → 원인 → 선택지 → 권장 조치 |
| 미래 사업/전략 | 핵심 답변 → 현재 위치 → 미래 변화 → 기회 → 전략적 선택 → 실행/위험 |

실제 흐름은 다음 순서를 따른다.

```text
질문
  → answer_requirements
  → 필요한 evidence requirements
  → 실제 확보·검증된 근거
  → block eligibility
  → 질문 직접성 + 목적별 reader flow
  → block 선택·배치
```

- 동일한 목적이라도 질문 형태와 확보된 근거에 따라 블록 종류와 순서는 달라질 수 있다.
- KPI, LANDSCAPE, BAR, TABLE, SWOT 같은 구체 블록명은 narrative 표에 넣지 않는다.
  같은 의미도 데이터 형태에 따라 chart, landscape, bar, benchmark table, matrix 등으로
  다르게 표현할 수 있다.
- 표 순서를 맞추려고 불필요한 정보를 수집하거나 블록을 생성하지 않는다.
- 질문에 직접 답하는 내용이 첫 독해 지점이다. 이후 위→아래·왼쪽→오른쪽으로 자연스럽게
  읽히게 배치한다.
- slot lead를 먼저 정하고 미표현 근거가 있을 때만 companion을 붙이는 2패스는
  eligibility 이후의 렌더링 규칙으로 유지한다.

### 8-2. 수집 예산을 옮기기 전에 **수율부터 비교**한다

초기 수집 비중을 줄이고 부족 근거 재수집을 강화할지는 아직 결정되지 않았다. 다음
지표를 같은 실행 JSON에서 1차 수집과 추가수집으로 나눠 비교한 뒤 결정한다.

1. `answer_requirements`별 관련 문서 수와 독립 출처 수
2. analyzer를 통과한 관련 문서 비율
3. evidence requirement를 충족한 metric/comparison/factor/action 수
4. 최종 lead/companion 블록에 채택된 근거 수
5. API 호출·문자·토큰당 채택 근거 수

추가수집은 단순히 문서를 더 가져오는 단계가 아니다. **아직 충족되지 않은 질문의
evidence requirement**(예: 연령대 × 같은 매체 reach, 회사 × 같은 비교 기준)를
검색어와 analyzer 추출 목표로 넘겨야 한다. 특정 블록을 그리기 위해 검색하지 않는다.
추가수집 문서가 0건이어도 기존의 검증된 근거로 계속하는
방어는 `d785cad`에 들어갔다. 반대로 문서가 생겼다는 이유만으로 성공으로 판단하지
않는다.

### 8-3. 2026-08-09 실제 실행 기록은 파이프라인 완주지만 **품질 회귀**였다

- 재현 결과: `storage/requests/req_ui_bd88e065.result.json`
- 질문: `SK브로드밴드 브랜드 이미지 개선에 맞는연령층별 광고 매체 및 모델 추천`
- 조건: 실무진 / SK Broadband / Streamlit 실제 질문창 실행
- 회귀가 발생한 코드 기준: `d785cad` (`a53b775`에서 revert 완료, 이후
  `9dfb515`의 목적 라우팅·근거 블록 개선과 `2f2ba86`의 hardening이 추가됨)
- 실행 결과: 문서 8건, 분석 5건, grounded claim 107건, 파이프라인 전 단계 `ok`
- 보존된 요구사항:
  1. SK브로드밴드 브랜드 이미지 개선 전략
  2. 연령층별 광고 매체 추천
  3. 연령층별 광고 모델 추천

그러나 결과물은 이전보다 나빠졌다.

- 단기 마케팅 기획 질문을 `future_business`로 분류해 미래사업 슬롯 흐름을 적용했다.
- 식음료 마케팅, 삼성 대표기업, KOFIC 영화산업 자료처럼 질문 주변의 자료가 섞였다.
- 연령대 × 동일 매체 reach와 연령대 × 모델의 공통 비교축을 만들지 못했다.
- 긴 설명문 3개가 `comparison_points`처럼 취급됐다.
- `recommended_actions=0`인데 요약은 실행 전략을 단정했다.
- 최종 화면은 `시장 변화` 산문과 `필요 역량` 표 위주였으며, 질문의 핵심 블록을
  전달하지 못했다.
- 추가수집은 기술적으로 완료됐지만 KOFIC 2건을 더 가져온 것이므로, 이번 결과를
  근거로 초기 수집 예산을 줄이면 안 된다.

따라서 다음 작업은 코드를 먼저 고치는 것이 아니라 이 결과와 직전 상대적으로 나았던
결과를 단계별로 비교하는 것이다. 최소 비교 지점은 목적 분류 → 검색 질의 → 문서 관련성
판정 → 요구사항별 근거 묶음 → block contract → 슬롯 선택 → 요약/행동 일치성이다.

### 8-4. 구현 완료 / 미완료 / 다음 개선

**완료·유지할 것**

- 질문에서 뽑은 `answer_requirements`가 수집·분석 단계까지 전달된다 (`6830b9e`).
- 부족 요구사항이 있으면 bounded 추가수집 기회를 준다.
- 추가수집 실패가 기존 유효 근거까지 버리거나 전체 파이프라인을 중단하지 않는다
  (`d785cad`).
- Solar Pro 3를 entity / synthesis / sk_broadband analyzer에 쓰는 운영 방침은 유지한다.
  BASE_URL과 모델명은 서로 다른 설정이며, 실제 `.env` 값은 에이전트가 수정하지 않는다.
- report-generator payload 중복 축소, 근거 추적, 결정론적 블록 계약, 슬롯 2패스,
  가로형 레이아웃 원칙은 유지한다.

**미완료·개선 필요**

1. 목적 분류가 단순 `추천/전략` 신호를 미래사업으로 과대 해석하는지 실제 사례군으로
   감사한다.
2. 요구사항을 보존하는 데서 끝내지 말고, 각각을 `충족/부분충족/미충족`으로 판정하고
   근거와 최종 블록까지 연결한다.
3. 질문·계열사·비교축과 먼 문서는 analyzer 이전/이후 어느 단계에서 제거할지 수율을
   보고 결정한다. 단순 키워드 포함만으로 관련 있다고 판단하지 않는다.
4. `comparison_points`에는 비교 주체·공통 기준·값/등급이 실제로 있어야 한다. 일반
   권고 문장이나 긴 산문은 비교 블록 입력이 아니다.
5. `recommended_actions=0`일 때 요약/리포트 작성기가 근거 밖의 실행 전략을 새로
   단정하지 못하게 계약 일치성을 검증한다.
6. 청중별 어조·정보 밀도·블록 순서 변화는 아직 완성되지 않았다. 블록을 버리는 방식이
   아니라 같은 근거를 청중에 맞춰 압축·강조하는 방식이어야 한다.
7. 실제 질문 9개를 특수 처리하지 않고 회귀 픽스처/평가 세트로 사용한다.

### 8-5. 도혁님/소스 담당 에이전트와의 작업 경계

도혁님은 소스단과 팀장 AI 실험을 먼저 진행할 예정이다. 서로 같은 문제를 다른 층에서
중복 수정하지 않도록 다음처럼 나눈다.

**도혁님 우선 범위**

- `sources/registry/**`, sector collector, 검색 질의 생성·재검색, 문서 관련성/중복 제거
- 1차 수집과 evidence requirement 보강 수집의 수율 로그 및 비교
- 팀장 AI를 넣는다면 수집 결과를 지휘·재질의하는 역할로 제한하고, 구조화된
  `answer_requirements`와 부족한 `evidence requirements`를 입력/출력으로 남기기
- “문서 수 증가”가 아니라 질문 요구사항을 실제로 채운 검증 근거 수로 평가

**사용자/Codex 우선 범위**

- 목적 분류와 목적별 reader flow
- `block_shapes.py`, `purpose_slots.py`, 블록 렌더링과 한 화면 레이아웃
- 청중별 표현·정보 밀도·강조 순서
- synthesis/report/layout 사이의 근거·행동 일치성

**공유 변경 전 알릴 것**

- `common/contracts.py`, `pipeline.py`, analyzer/synthesis 프롬프트처럼 양쪽 경계를
  바꾸는 파일
- 요구사항 스키마, metric/comparison/action 계약, 수집 trace 필드
- 목적 reader flow, evidence requirement 또는 블록 eligibility 계약

가능하면 담당별 브랜치/작업 트리를 분리하고, 상대 변경을 읽기 전 대규모 리팩터링이나
공통 파일 수정을 피한다. 팀장 AI도 최종 블록을 임의 선택하거나 근거 없는 값을 채우면
안 된다. 최종 블록 선택은 계속 결정론적 계약이 담당한다.

### 8-6. `9dfb515` / `2f2ba86` 이후 현재 hardening 상태

아래는 이미 구현됐으므로 다시 별도 구조를 만들거나 과거 방식으로 되돌리지 않는다.

**목적·슬롯·블록**

- `common/purpose_slots.py`가 네 목적의 narrative slot 순서와 후보 블록 우선순위를
  담당한다. 최종 `resolve_slots()`는 lead-first 2패스를 유지한다.
- `common/block_shapes.py`는 UI와 분리된 블록 적격성 계약이다. line/bar/KPI뿐 아니라
  landscape, grouped bar, share split, ranking, benchmark, level/decision matrix,
  cause tree 등의 입력 조건을 판정한다.
- `reporting/dashboard_streamlit/blocks/slot_blocks.py`가 live Streamlit 슬롯 렌더러의
  단일 등록 지점이다. `blocks/purpose_templates.py`는 보조적 선언 문서이며 현재 슬롯
  선택의 source of truth가 아니다.
- 질문의 명시 요구(비교·추이·추천·원인·대응)는 purpose만 바꾸는 단일 키워드가 아니라
  `question_answer_type`과 `answer_requirements`에서 evidence requirement로 구체화한다.
  수집 이후에는 eligibility와 reader flow가 표현 블록과 순서를 정한다.

**Evidence structuring**

- `MetricPoint`는 절대값 외에 원문이 직접 말한 상대지표를
  `is_relative` / `comparison_period` / `value_origin`으로 보존한다. 상대지표에서
  보이지 않는 절대값을 계산하거나 단일 배수를 가짜 시계열로 만들지 않는다.
- metric grouping은 label alias가 같아도 unit, `share_of`, time basis, 상대/절대 속성이
  다르면 한 계열로 합치지 않는다.
- landscape는 같은 topic·geography·time context가 있는 데이터만 결합한다. 관련 없는
  headline KPI를 붙여 복합 블록을 성립시키지 않는다.
- 정성 `high/medium/low`는 원문이 직접 수준을 평가한 경우만 허용한다. 수치 크기나
  긍정 표현만 보고 level을 만들지 않는다.
- 인과 edge와 importance는 `sk_broadband` analyzer가 근거·대상 claim·cycle·basis를
  검증한 뒤에만 보존한다. 다른 섹터에 같은 계약을 확장할 때 이 검증을 우회하지 않는다.

**명시 alias 계약**

- 엔터티·지표 통합은 `common/content_quality_validator.py`의 작은 명시 계약으로만 한다.
  fuzzy matching을 추가하지 않는다.
- HBM 쪽은 Samsung Electronics/삼성전자, SK hynix/SK하이닉스,
  Micron Technology/마이크론과 검토된 시장규모 표현을 지원한다.
- SK브로드밴드 쪽은 SK Broadband/SK브로드밴드/SKB, KT, LG Uplus 및 주요 OTT·숏폼
  플랫폼의 bilingual alias를 지원한다. 단, `B tv = SK Broadband`,
  `Genie TV = KT`처럼 서비스와 회사를 같은 엔터티로 합치지 않는다.
- IPTV/초고속인터넷/OTT 가입자, 이용률·점유율·시청시간, 광고 reach, ARPU, churn,
  브랜드 인지도·선호도, 모델 선호·브랜드 적합도, 롱폼·숏폼, 셋톱박스 원가처럼
  서로 다른 측정값은 분리한다. 문자열이 비슷하다는 이유로 통합하지 않는다.

이 상태의 회귀 기준은 `python -m pytest -q`의 **878 passed, 2 skipped**다. 문서만
고치는 작업에서는 코드·프롬프트·테스트를 함께 바꾸지 않는다.
