"""Source Router runtime configuration.

Everything doc1 describes as a threshold or a stop-policy number lives here
as a plain field rather than a hardcoded constant deep in a function — doc2
§13's "configurable, not hardcoded business truth" point applies even though
this build otherwise treats doc2 as non-blocking guidance (see plan file).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRouterConfig:
    # Model overrides. None (default) lets each module resolve its own model
    # from its own env var — see planner.py/_solar.py/web_search.py. Set here
    # only to override without touching the environment (e.g. from a test or
    # a one-off script).
    planner_model: str | None = None
    search_model: str | None = None

    # Live-verified 2026-08-09: a `tool_choice="required"` web_search call
    # (web_search.py) genuinely took 42.3s end-to-end for a real query - not
    # an artifact of the old hard client-side timeout= kwarg (that was fixed
    # separately, see web_search.py's module docstring), just real latency
    # for this call shape. 30s was cutting off calls that would have
    # succeeded; 60s leaves real margin above the one measured sample.
    # Raised again 2026-08-11 (temporary stopgap): a live run combining two
    # parallel topics into one quoted-phrase query ("롱폼과 숏폼 미디어 소비
    # 트랜드") timed out on every attempt at 60s, burning search budget for
    # zero evidence. 90s buys more margin while the actual fix (splitting
    # such queries before they're ever sent, see planner_common_tail.md) is
    # rolled out.
    call_timeout_seconds: int = 90

    # doc1 §4's query-count guidance is prompt-level (told to the planner),
    # not enforced numerically — these are hard ceilings applied on top,
    # regardless of how many the planner returns. Raised 5/3 -> 15/15
    # (2026-08-09): a live run against a real question (판례: "중앙그룹 회생
    # 사태") showed a hand-curated query set using specific regulatory-body +
    # exact-term combinations found real primary sources this router's
    # smaller, more generic query set missed entirely — planner.md's own
    # STEP 4 target table decides how many of these 15 slots actually get
    # used per question (strict "simple question" criteria added there so
    # this higher ceiling doesn't just pad every question with filler
    # queries). Real enforcement backstop stays max_web_search_calls below.
    max_priority1_queries: int = 8
    max_priority2_queries: int = 6
    # Planner + refiner share this plan-level cap. It is intentionally lower
    # than the old 15+15 parallel prototype; direct queries are reserved first.
    max_planned_queries: int = 12

    # doc1 §25/§27 stop policy. The loop always terminates within these
    # bounds, however the model behaves. max_gap_loop_iterations deliberately
    # kept at 3 even though the caps above were raised (2026-08-09) — see
    # coverage.py's check_coverage(): every iteration resends the ENTIRE
    # accumulated results pool, so raising this together with max_results
    # multiplies cost (iterations x pool size) rather than just adding to
    # it; raising query/result ceilings alone stays roughly linear.
    max_gap_loop_iterations: int = 3
    # sources_to_inspect is already naturally bounded by the `results` pool
    # size (coverage.py drops any url not in that round's known_urls), which
    # is itself capped at max_results below — so this is a defensive ceiling
    # decoupled from that bound, not the primary throttle. Kept equal to
    # max_results so it doesn't bind in practice (same reasoning as before,
    # just at the new value) — coverage.md already only requests full-text
    # for genuinely deficient sources. NOTE: each inspection may be an
    # html_extractor.py (Firecrawl) call — Firecrawl is rate-limited to
    # ~10-11 req/min (see CLAUDE.md) — 15 sequential inspections in one run
    # can approach that limit; not currently paced/throttled here.
    max_sources_to_inspect: int = 15
    # Hard ceiling on total GPT-5 mini web_search calls per run - planner,
    # refiner and every gap-loop follow-up draw on this one allowance, so a
    # long run cannot spend a fresh budget per tier. router._search_budget()
    # then picks the run's actual budget below this, from the question's own
    # comparison/trend/response complexity and its evidence-need count.
    # Raised 12 -> 40 (2026-08-11, temporary stopgap alongside
    # _search_budget_terms()'s own increase): this ceiling clips whatever
    # _search_budget() computes via min(ceiling, budget), so raising the
    # per-question budget terms without raising this cap would have been a
    # no-op — a question that now scores 26 (base 14 + evidence_needs_bonus
    # 12) was previously being clipped down to 12 regardless.
    max_web_search_calls: int = 40

    # Cost guards added after a live-cost review found two uncapped points:
    # a single execute_web_search() call could return an unbounded number of
    # URLs (each with its own summary/key_facts, inflating that one call's
    # output tokens), and the accumulated `results` pool was resent in full
    # on every check_coverage() call with no size limit — so the same
    # oversized round got re-billed on every gap-loop iteration, not just
    # once. Both are enforced in code, not just asked for in the prompt
    # (mirrors ai_search_harness.py's max_candidates_per_round /
    # max_total_scrape_calls, which this router otherwise didn't have an
    # equivalent of). max_urls_per_query deliberately left at 2 (2026-08-09)
    # even while raising everything else — this is the one cap that bounds a
    # single web_search call's own output size, independent of how many
    # queries/rounds run.
    max_urls_per_query: int = 2
    max_results: int = 15

    # PDF size routing (doc1 §11). Token counts are estimated from character
    # count when no real tokenizer is available — see pdf_parser.py.
    pdf_small_max_tokens: int = 25_000
    pdf_large_max_tokens: int = 80_000
    pdf_chars_per_token_estimate: float = 2.2

    min_content_length: int = 250
    max_evidence_chars_for_coverage_check: int = 6_000
