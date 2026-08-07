"""Two things the ad-media re-run exposed, generalised.

Neither is about that question: any document the AI search harness finds
carries a bare domain as its source_id, and any query can come back with a
different yield on a retry.
"""

from __future__ import annotations

from common.contracts import (
    DocumentAnalysis,
    PlannedSource,
    SourcePlan,
)
from core.synthesis.synthesizer import synthesize
from reporting.dashboard_streamlit import components
from sources.collectors.ai_search_harness import (
    record_query_yield,
    reset_query_yield_history,
)


class _Result:
    def __init__(self, analyses, planned=()):
        self.document_analyses = analyses
        self.source_plan = SourcePlan(
            request_id="r", sector_id="sk_broadband", planned_sources=list(planned)
        )


def _analysis(doc_id, source_id, url=None, title=None):
    return DocumentAnalysis(
        doc_id=doc_id, source_id=source_id, source_url=url, source_title=title, summary="s"
    )


# --- source links ------------------------------------------------------


def test_source_list_links_to_the_document_not_a_registered_homepage():
    """AI-harness finds carry a bare domain as source_id, which matches no
    registered source name - so every row fell through to "링크 없음" while
    the article URL sat unused on the analysis."""
    result = _Result([
        _analysis("www.ajupress.com:a1", "www.ajupress.com", "https://www.ajupress.com/x")
    ])

    markup = components.render_source_list(result)

    assert "https://www.ajupress.com/x" in markup
    assert "링크 없음" not in markup


def test_source_list_falls_back_to_the_registered_url():
    result = _Result(
        [_analysis("etnews:a1", "전자신문")],
        planned=[PlannedSource(name="전자신문", url="https://www.etnews.com")],
    )

    markup = components.render_source_list(result)

    assert "https://www.etnews.com" in markup


def test_source_list_says_so_honestly_when_there_is_no_url():
    result = _Result([_analysis("x:a1", "알 수 없는 출처")])
    assert "링크 없음" in components.render_source_list(result)


def test_each_source_appears_once():
    result = _Result([
        _analysis("d:1", "www.etnews.com", "https://www.etnews.com/1"),
        _analysis("d:2", "www.etnews.com", "https://www.etnews.com/2"),
    ])
    assert components.render_source_list(result).count("<li>") == 1


def test_synthesis_carries_each_document_url():
    """So any renderer resolving a [doc_id=...] tag can reach the article,
    not just the dashboard panel that happens to hold the analyses."""
    synthesis = synthesize("r", "sk_broadband", [
        _analysis("www.etnews.com:a1", "www.etnews.com", "https://www.etnews.com/a"),
        _analysis("no.url:b1", "no.url"),
    ])

    assert synthesis.doc_url_map == {"www.etnews.com:a1": "https://www.etnews.com/a"}


def test_layout_sources_block_carries_the_url():
    from core.layout_generator.generator import _structure_evidence

    structured = _structure_evidence(
        ["매출이 늘었다 [doc_id=d:1]"],
        {"d:1": "www.etnews.com"},
        {"d:1": "https://www.etnews.com/a"},
    )

    assert structured[0]["source_url"] == "https://www.etnews.com/a"
    assert structured[0]["source_id"] == "www.etnews.com"


# --- search reproducibility --------------------------------------------


def test_identical_query_with_a_wildly_different_yield_is_flagged():
    """Live-observed: one query returned 0 candidates and the identical string
    on the recollection pass returned 5. Without this the report's contents
    depend on which attempt the reader happened to get, and a flaky search is
    indistinguishable from "no such evidence exists"."""
    reset_query_yield_history()

    assert record_query_yield("같은 쿼리", 0) is None
    warning = record_query_yield("같은 쿼리", 5)

    assert warning is not None
    assert "UNSTABLE" in warning


def test_ordinary_jitter_is_not_flagged():
    reset_query_yield_history()
    record_query_yield("q", 4)
    assert record_query_yield("q", 5) is None


def test_a_query_that_never_finds_anything_is_not_called_unstable():
    """Consistently zero is a real answer about the evidence, not flakiness."""
    reset_query_yield_history()
    record_query_yield("q", 0)
    assert record_query_yield("q", 0) is None


def test_history_does_not_leak_between_runs():
    reset_query_yield_history()
    record_query_yield("q", 0)
    reset_query_yield_history()
    assert record_query_yield("q", 5) is None
