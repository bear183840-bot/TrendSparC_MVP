# TrendSparC_MVP

AI Trend Intelligence platform for SK 계열사 staff (SK하이닉스 / SK브로드밴드 /
SK플래닛). A user submits a question (+ optional attachments, target
audience, target sector) → the pipeline classifies intent/entities, routes
to a sector, collects & analyzes real news via that sector's adapter,
synthesizes across documents, and adapts the result for a target **audience**
(who the *report* is shown to — external / practitioner / executive /
management — not who asked the question).

**Note:** `README.md` is currently stale (predates most of the work below —
still says all sectors are `template_only` and references a deleted
`core/intent/` module). Trust this file and the code over `README.md` until
someone updates it.

## Core design principles (do not violate these)

- **Contract isolation**: every block boundary communicates only through
  Pydantic models in `common/contracts.py`. Never branch on a literal
  sector/audience *name* anywhere — always resolve behavior through a
  registered `profile.json` / audience profile file instead.
- **Failure traceability**: every stage records a `StageTrace`
  (`common/errors.py`); a stage that can't run raises `PipelineStageError`
  with `reason="template_only: ..."` rather than faking data.
- **Dynamic discovery, zero hardcoding in `core/`**: `core/sector_router`
  scans `sectors/*/profile.json` at runtime. Adding a sector = new folder +
  `profile.json`, no `core/` changes. Same for audiences
  (`audience/profiles/*.md`) and cross-sector sources
  (`sources/registry/common/*.json`, merged into every sector's `SourcePlan`).
- **No fabrication, ever**: no invented facts, no arbitrary reliability
  tiers for unregistered sources, no fake analysis when a stage isn't
  implemented (`prompts/global_system_prompt.md` has the full list).
- **1st-pass rule-based → 2nd-pass AI-based, silent fallback**: this pattern
  repeats three times — `core/entity/{extractor.py,ai_based.py}`,
  `core/synthesis/{synthesizer.py,ai_based.py}` — and analyzer's use of
  OpenAI per sector. The AI pass is always optional; missing key / API
  failure / refusal must silently fall back to the rule-based result, never
  break the pipeline.

## Pipeline stages (`core/request_pipeline/pipeline.py`)

```
UserRequest
  -> entity            (rule-based + AI refinement; also classifies primary_intent)
  -> sector_router      (scans sectors/*/profile.json, matches aliases/keywords)
  -> source_planner     (sector registry + sources/registry/common/ merged in)
  -> sector_adapter     collector -> processor -> validator -> analyzer  (per-sector code)
  -> synthesis          (concatenate key_points; AI pass dedupes/ranks/summarizes)
  -> report_planner     (audience profile's focus + primary_intent's report_structures template)
  -> audience_adapter   (⚠️ still just copies highlights verbatim — see Known gaps)
  -> layout_generator   (structural block placement only, no rendering)
```

`dry_run=True` (main.py's default) skips the sector_adapter stage entirely.
`--no-dry-run` invokes the real adapter — costs real API money if keys are set.

## Sector status (accurate as of this file's last edit — verify against code before trusting)

| Sector | profile.json / sources.json | system_prompt.md | adapter (collector/processor/validator/analyzer) |
|---|---|---|---|
| `sk_hynix` | done | done (8-angle framework) | **real**, implemented |
| `sk_planet` | done | done (very detailed — scope, glossary, importance tiers, cross-sector table, audience emphasis) | **real**, implemented |
| `sk_broadband` | done (team PR merged) | done (team PR merged) | still stub (`template_only`) |
| `general` (fallback) | minimal | empty template | still stub — intentionally deferred, not planned yet |

`sk_hynix` and `sk_planet`'s collectors are functionally identical (same
file, same logic, different `_STAGE`/env var names) — if you fix a bug in
one, fix it in the other too, or better, consider extracting the shared
logic.

## Known gaps (not obvious from reading the code alone — read this before assuming something works)

- **`audience/adapter.py` doesn't actually adapt anything yet.** It copies
  `synthesis.highlights` verbatim into every section regardless of audience
  tone/detail_level. This is the single biggest confirmed gap — a real
  LLM-based rewrite step per audience is needed. `audience/profiles/*.md`'s
  DRAFT content (tone/detail_level/focus) and each sector's
  `system_prompt.md`'s "대상별 강조 포인트" section (sector-specific: which
  topics matter to which role) are both meant to feed this once it's built
  — see `sectors/sk_hynix/prompts/system_prompt.md` / `sk_planet`'s
  equivalent for the pattern (analyzer already combines
  `global_system_prompt.md` + sector prompt this same way).
- **`prompts/report_structures/{current_status,issue_response,future_business,root_cause}.md`
  are empty placeholders.** `report_planner` wires `primary_intent` into
  `ReportPlan.intent_emphasis` correctly, but there's no actual
  per-intent differentiation content yet — team needs to design and fill these.
- **`core/entity/ai_based.py`'s organizations/technologies classification
  is unreliable.** Live-tested: gpt-4o-mini keeps putting named
  brands/products (e.g. "OK캐쉬백", "Syrup") into the generic `keywords`
  field instead of `organizations`/`technologies`, even after prompt
  clarification. Deferred until all sectors are implemented. This matters
  because `pipeline.py` builds `search_terms = [*organizations,
  *technologies, *keywords]` — if orgs/tech were populated correctly, the
  collector's query would naturally lead with the most distinctive terms.
- **`reporting/dashboard_streamlit/renderer.py` is still a stub.**
  `reporting/dashboard_streamlit/app.py` (the real, working intake UI)
  bypasses it and renders `DynamicLayout` blocks as plain `st.json` — swap
  this out once someone implements the real renderer against the Figma
  design.
- **sk_broadband has no real adapter yet** — profile/prompt are ready,
  someone needs to implement `collector/processor/validator/analyzer`
  following the sk_hynix/sk_planet pattern exactly (Firecrawl `search()`
  per source, OpenAI Structured Outputs analyzer).
- **`general` sector is deliberately unimplemented** — only gets the common
  source registry (Naver) wired into its `SourcePlan`; no real
  collector/analyzer. Not currently planned.

## Technical gotchas learned the hard way (live-verified, not guessed)

- **Firecrawl's `search()` treats multiple query terms as roughly an AND.**
  A long query (bilingual Korean+English duplicate pairs, or mixing
  specific brand names with generic filler words like "포인트"/"마케팅"/"현황")
  can return zero results even when a 1-2 term version of the same query
  succeeds. Collectors now try **short queries first** (`_PRIMARY_TERM_COUNT
  = 2`, then 1, then the full length as a last resort) — trying the
  longest/most-restrictive query first wastes a call on the attempt least
  likely to succeed, for every source, every time.
- **This Firecrawl plan is rate-limited to ~10-11 requests/minute.** With
  up to 3 search attempts per source and 6 sources registered, worst case
  is ~18 calls per pipeline run — short-first ordering keeps the realistic
  case well under the limit since most sources succeed on the first
  (cheapest) attempt.
- **Collector fetches up to 3 documents per source**
  (`_MAX_RESULTS_PER_SOURCE = 3`), not just 1 — a source whose top hit is
  mediocre, or other sources returning nothing, still contributes.
- **`sources/registry/common/*.json` is merged into every sector's
  `SourcePlan` automatically** (`core/source_planner/planner.py`) —
  currently holds one Naver News entry. Register something here only if
  it's genuinely useful across all sectors, not sector-specific.
- **Registered source URLs should point at actual news/article sections,
  not root domains** — verified live for sk_planet: a bare `www.etnews.com`
  vs. its actual `/news/section.html?id1=04` section made a real difference
  in Firecrawl's indexed coverage. Some sites (SK플래닛's own site,
  모바일인덱스) genuinely have no distinct section to link to — documented
  in their `reliability_reason`, left as root domain, not fabricated.
- **Windows console**: `main.py` calls `sys.stdout/stderr.reconfigure(encoding="utf-8")`
  — without it, Korean text crashes on cp949 consoles. Bash-tool console
  output in this dev environment often mangles Korean text on `print()` /
  `cat` (cp949 codepage) even when the underlying file is correctly UTF-8 —
  verify file correctness via the `Read` tool, not by trusting garbled
  terminal output.
- **`st.markdown(..., unsafe_allow_html=True)` in the Streamlit app**: any
  line indented 4+ spaces in the HTML string gets misread as a Markdown
  code block, silently breaking HTML rendering (shows raw tags as text).
  Use the `_html()` helper in `reporting/dashboard_streamlit/app.py`
  (wraps `textwrap.dedent`), don't call `st.markdown` directly with
  indented multi-line f-strings.
- **`.env` needs manual editing** — `load_dotenv()` is called in `main.py`,
  but no code can or should read/write actual key *values* on the user's
  behalf. `.env.example` documents every var; the user edits `.env` by hand.

## Env vars (see `.env.example` for the authoritative, up-to-date list)

Each sector's analyzer has its own key (`TRENDSPARC_SK_HYNIX_ANALYZER_API_KEY`,
`TRENDSPARC_SK_PLANET_ANALYZER_API_KEY`, ...). Shared/sector-agnostic AI
passes (`TRENDSPARC_ENTITY_AI_API_KEY`, `TRENDSPARC_SYNTHESIS_AI_API_KEY`)
and `FIRECRAWL_API_KEY` are shared across all sectors. All of these are
optional in the sense that missing ones degrade gracefully (rule-based
fallback, or a `template_only` trace entry) rather than crashing.

## Running things

```bash
pytest -q                                              # full suite, no API keys needed
python main.py --question "..." [--sector X] [--audience Y]              # dry-run, free
python main.py --question "..." --sector sk_hynix --no-dry-run           # REAL API calls, costs money
streamlit run reporting/dashboard_streamlit/app.py                       # intake UI
```

## Working conventions for this repo

- **Never commit or push without an explicit request in the same
  conversation**, even right after finishing a fix.
- **Never ask the user to paste real API key values into chat.** If a
  `.env` needs a new entry, add the empty placeholder to `.env.example`
  and tell the user to fill in `.env` themselves in an editor.
- Give plans/explanations in Korean when the user has been conversing in
  Korean.
- Before recommending "just use the real production API keys," check
  whether a free/dry-run/no-cost verification path exists first
  (`dry_run=True`, or forcing env vars empty) — several bugs this session
  were found and fixed without spending any real API money.
