import time
import types

import pytest

from common.contracts import PlannedSource
from common.errors import PipelineStageError
from sectors.sk_hynix.adapter.collector import _crawl_source


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
