"""Best-case probe: with every call succeeding and coverage always asking for
more, how many original_source documents can research() actually return?

No network — planner/web_search/coverage/extract_html are all faked to be
maximally generous, so the only thing bounding the result is the router's own
arithmetic.
"""
import itertools
import sys

sys.path.insert(0, ".")

from sources.collectors.source_router import coverage as coverage_module
from sources.collectors.source_router import planner as planner_module
from sources.collectors.source_router import router as router_module
from sources.collectors.source_router import web_search as web_search_module
from sources.collectors.source_router.config import SourceRouterConfig
from sources.collectors.source_router.contracts import (
    CoverageDecision,
    EvidenceVerification,
    KeyFact,
    NextQuery,
    SearchPlan,
    SearchPlanQuery,
    SourceToInspect,
    WebSearchResult,
)

CONFIG = SourceRouterConfig()

# 8 priority-1 queries — the most the router will run (max_priority1_queries)
PLAN = SearchPlan(
    intent="probe",
    queries=[
        SearchPlanQuery(query=f"d{i}", angle="a", purpose="p", priority=1, query_role="direct")
        for i in range(CONFIG.max_priority1_queries)
    ] + [
        SearchPlanQuery(query=f"s{i}", angle="a", purpose="p", priority=2, query_role="supporting")
        for i in range(CONFIG.max_priority2_queries)
    ],
)

_url_counter = itertools.count()


def fake_search(query, **_):
    """Every call returns the max number of brand-new URLs."""
    return [
        WebSearchResult(
            url=f"https://ex.com/{next(_url_counter)}",
            title="t",
            summary="s",
            key_facts=[KeyFact(text="f")],
        )
        for _ in range(CONFIG.max_urls_per_query)
    ]


def fake_coverage(question, search_plan, results, **_):
    """Never satisfied; always wants every pooled URL inspected and more
    searches run."""
    return CoverageDecision(
        sufficient=False,
        needs_full_text=True,
        sources_to_inspect=[
            SourceToInspect(url=r.url, reason="need text") for r in results
        ],
        next_queries=[
            NextQuery(query=f"gap{i}", purpose="p", priority=2)
            for i in range(CONFIG.max_priority2_queries)
        ],
        reason="gap",
    )


planner_module.plan_searches = lambda question, **_: PLAN
web_search_module.execute_web_search = fake_search
coverage_module.check_coverage = fake_coverage
coverage_module.verify_evidence = lambda *a, **k: EvidenceVerification()
router_module.html_extractor.extract_html = lambda url, **_: "원문 " * 200

result = router_module.research("probe question", CONFIG)

originals = [r for r in result.results if r.evidence_depth == "original_source"]
print(f"max_results                     = {CONFIG.max_results}")
print(f"max_auto_inspect_direct_results = {CONFIG.max_auto_inspect_direct_results}")
print(f"max_sources_to_inspect          = {CONFIG.max_sources_to_inspect}")
print(f"max_gap_loop_iterations         = {CONFIG.max_gap_loop_iterations}")
print("-" * 50)
print(f"total results in pool           = {len(result.results)}")
print(f"ORIGINAL SOURCES RETURNED       = {len(originals)}")
print(f"search calls used               = {result.search_calls_used} / {result.search_budget}")
print(f"stop_reason                     = {result.stop_reason}")
