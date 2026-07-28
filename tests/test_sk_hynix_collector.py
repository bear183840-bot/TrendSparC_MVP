import time
import types

import pytest

from common.contracts import PlannedSource, SourcePlan
from common.errors import PipelineStageError
from sectors.sk_hynix.adapter import collector as collector_module
from sectors.sk_hynix.adapter.collector import _crawl_source, collect


def _make_result(markdown, title=None, url=None, published_time=None):
    metadata = types.SimpleNamespace(title=title, url=url, published_time=published_time)
    return types.SimpleNamespace(markdown=markdown, metadata=metadata, title=title, url=url)


def _search_data(results):
    return types.SimpleNamespace(web=results)


class _SlowClient:
    """A client whose search() never returns within the test's shortened timeout."""

    def search(self, query, include_domains, limit, scrape_options):
        time.sleep(5)
        raise AssertionError("should never be reached — the timeout should give up first")


class _FastClient:
    def __init__(self, results):
        self._results = results

    def search(self, query, include_domains, limit, scrape_options):
        return _search_data(self._results)


class _ErrorClient:
    def search(self, query, include_domains, limit, scrape_options):
        raise RuntimeError("simulated network failure")


def test_crawl_source_gives_up_after_timeout_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(collector_module, "_SEARCH_TIMEOUT_SECONDS", 1)
    source = PlannedSource(name="slow source", url="https://example.com/news/")

    start = time.monotonic()
    documents = _crawl_source(_SlowClient(), source, ["HBM4"])
    elapsed = time.monotonic() - start

    assert documents == []
    assert elapsed < 3  # well under a real search timeout — proves it didn't block


def test_crawl_source_returns_document_from_top_search_result():
    result = _make_result(
        "# HBM4 기사 본문",
        title="HBM4 양산 발표",
        url="https://example.com/news/hbm4-launch/",
        published_time="2026-01-01T00:00:00+09:00",
    )
    source = PlannedSource(name="fast source", url="https://example.com/news/")

    documents = _crawl_source(_FastClient([result]), source, ["HBM4"])

    assert len(documents) == 1
    assert documents[0].url == "https://example.com/news/hbm4-launch/"
    assert documents[0].title == "HBM4 양산 발표"
    assert documents[0].content == "# HBM4 기사 본문"


def test_crawl_source_returns_empty_when_no_search_results():
    source = PlannedSource(name="empty source", url="https://example.com/news/")

    documents = _crawl_source(_FastClient([]), source, ["HBM4"])

    assert documents == []


def test_crawl_source_returns_empty_without_keywords():
    source = PlannedSource(name="no keywords", url="https://example.com/news/")

    # No client call should even be attempted — _FastClient would raise via
    # AssertionError-free path anyway, but the point is keywords=[] short-circuits.
    documents = _crawl_source(_FastClient([_make_result("content")]), source, [])

    assert documents == []


def test_crawl_source_still_raises_on_a_real_failure():
    source = PlannedSource(name="broken source", url="https://example.com/news/")

    with pytest.raises(PipelineStageError):
        _crawl_source(_ErrorClient(), source, ["HBM4"])


def _make_source_plan(source_count: int, keywords: list[str] | None = None) -> tuple[SourcePlan, list[PlannedSource]]:
    sources = [
        PlannedSource(name=f"source-{i}", url=f"https://example.com/{i}/") for i in range(source_count)
    ]
    plan = SourcePlan(
        request_id="req_test", sector_id="sk_hynix", planned_sources=sources, question_keywords=keywords or []
    )
    return plan, sources


class _PerSourceClient:
    """A fake Firecrawl client whose search() behavior is looked up per source domain."""

    def __init__(self, behavior_by_domain):
        self._behavior_by_domain = behavior_by_domain

    def search(self, query, include_domains, limit, scrape_options):
        domain = include_domains[0]
        behavior = self._behavior_by_domain[domain]
        if isinstance(behavior, Exception):
            raise behavior
        return _search_data(behavior)


@pytest.mark.parametrize("source_count", [3, 4, 5])
def test_collect_continues_past_one_failed_source_regardless_of_source_count(monkeypatch, source_count):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")

    plan, sources = _make_source_plan(source_count, keywords=["HBM4"])
    behavior_by_domain = {}
    for i, source in enumerate(sources):
        domain = f"{i}.example.com"  # each source gets its own domain to key behavior on
        if i == 1:  # the 2nd source fails, mirroring the real rate-limit case
            behavior_by_domain[domain] = RuntimeError("simulated rate limit")
        else:
            result = _make_result(f"content-{i}", title=f"title-{i}", url=source.url)
            behavior_by_domain[domain] = [result]

    # Rebuild sources so each has a distinct domain matching behavior_by_domain's keys.
    sources = [
        PlannedSource(name=f"source-{i}", url=f"https://{i}.example.com/") for i in range(source_count)
    ]
    plan = SourcePlan(
        request_id="req_test", sector_id="sk_hynix", planned_sources=sources, question_keywords=["HBM4"]
    )

    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: _PerSourceClient(behavior_by_domain))

    documents = collect(plan)

    failing_source_id = sources[1].name
    assert len(documents) == source_count - 1
    assert all(doc.source_id != failing_source_id for doc in documents)
