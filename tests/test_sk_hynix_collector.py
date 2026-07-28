import time
import types

import pytest

from common.contracts import PlannedSource, SourcePlan
from common.errors import PipelineStageError
from sectors.sk_hynix.adapter import collector as collector_module
from sectors.sk_hynix.adapter.collector import _crawl_source, collect


def _make_page(url, markdown, title=None, published_time=None):
    metadata = types.SimpleNamespace(url=url, title=title, published_time=published_time)
    return types.SimpleNamespace(markdown=markdown, metadata=metadata)


class _SlowClient:
    """A client whose crawl() never returns within the test's shortened timeout."""

    def crawl(self, url, limit, formats):
        time.sleep(5)
        raise AssertionError("should never be reached — the timeout should give up first")


class _FastClient:
    def __init__(self, pages):
        self._pages = pages

    def crawl(self, url, limit, formats):
        return types.SimpleNamespace(data=self._pages)


class _ErrorClient:
    def crawl(self, url, limit, formats):
        raise RuntimeError("simulated network failure")


def test_crawl_source_gives_up_after_timeout_instead_of_hanging(monkeypatch):
    monkeypatch.setattr("sectors.sk_hynix.adapter.collector._CRAWL_TIMEOUT_SECONDS", 1)
    source = PlannedSource(name="slow source", url="https://example.com/slow")

    start = time.monotonic()
    documents = _crawl_source(_SlowClient(), source)
    elapsed = time.monotonic() - start

    assert documents == []
    assert elapsed < 3  # well under the real 20s default — proves it didn't block


def test_crawl_source_parses_pages_into_source_documents():
    pages = [_make_page("https://example.com/a", "# Hello", title="Hello Page")]
    source = PlannedSource(name="fast source", url="https://example.com")

    documents = _crawl_source(_FastClient(pages), source)

    assert len(documents) == 1
    assert documents[0].content == "# Hello"
    assert documents[0].url == "https://example.com/a"
    assert documents[0].title == "Hello Page"


def test_crawl_source_still_raises_on_a_real_failure():
    source = PlannedSource(name="broken source", url="https://example.com")

    with pytest.raises(PipelineStageError):
        _crawl_source(_ErrorClient(), source)


class _PerSourceClient:
    """A fake Firecrawl client whose crawl() behavior is looked up per-URL."""

    def __init__(self, behavior_by_url):
        self._behavior_by_url = behavior_by_url

    def crawl(self, url, limit, formats):
        behavior = self._behavior_by_url[url]
        if isinstance(behavior, Exception):
            raise behavior
        return types.SimpleNamespace(data=behavior)


def _make_source_plan(source_count: int) -> tuple[SourcePlan, list[PlannedSource]]:
    sources = [
        PlannedSource(name=f"source-{i}", url=f"https://example.com/{i}") for i in range(source_count)
    ]
    plan = SourcePlan(request_id="req_test", sector_id="sk_hynix", planned_sources=sources)
    return plan, sources


@pytest.mark.parametrize("source_count", [3, 4, 5])
def test_collect_continues_past_one_failed_source_regardless_of_source_count(monkeypatch, source_count):
    # No real waiting in tests, and collect() builds its own Firecrawl client
    # internally, so both need to be monkeypatched at the module level.
    monkeypatch.setattr(collector_module, "_REQUEST_SPACING_SECONDS", 0)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")

    plan, sources = _make_source_plan(source_count)
    behavior_by_url = {}
    for i, source in enumerate(sources):
        if i == 1:  # the 2nd source fails, mirroring the real rate-limit case
            behavior_by_url[source.url] = RuntimeError("simulated rate limit")
        else:
            behavior_by_url[source.url] = [_make_page(f"{source.url}/a", f"content-{i}")]

    monkeypatch.setattr(collector_module, "Firecrawl", lambda api_key: _PerSourceClient(behavior_by_url))

    documents = collect(plan)

    failing_source_id = sources[1].name
    assert len(documents) == source_count - 1
    assert all(doc.source_id != failing_source_id for doc in documents)
