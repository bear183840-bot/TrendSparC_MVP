import types

import pytest

from common.contracts import PlannedSource, SourceDocument
from common.errors import PipelineStageError
from sectors.sk_innovation.adapter import analyzer as innovation_analyzer
from sectors.sk_innovation.adapter import collector as innovation_collector
from sectors.sk_innovation.adapter import validator as innovation_validator
from sectors.sk_planet.adapter import analyzer as planet_analyzer
from sectors.sk_planet.adapter import collector as planet_collector
from sectors.sk_planet.adapter import validator as planet_validator
from sectors.sk_telecom.adapter import analyzer as telecom_analyzer
from sectors.sk_telecom.adapter import collector as telecom_collector
from sectors.sk_telecom.adapter import validator as telecom_validator


class _Client:
    def search(self, query, include_domains, limit, scrape_options):
        metadata = types.SimpleNamespace(
            title="검증된 기사",
            url=f"https://{include_domains[0]}/article",
            published_time="2026-01-01T00:00:00+09:00",
        )
        item = types.SimpleNamespace(
            markdown="실제 수집 본문 " * 100,
            metadata=metadata,
            title=metadata.title,
            url=metadata.url,
        )
        return types.SimpleNamespace(web=[item])


@pytest.mark.parametrize("collector", [telecom_collector, innovation_collector, planet_collector])
def test_sector_collectors_only_build_documents_from_search_responses(collector):
    source = PlannedSource(
        name="공식 소스",
        url="https://example.com/news",
        collection_method=["firecrawl_search"],
        reliability_tier="official",
    )

    documents = collector._crawl_source(_Client(), source, ["AI", "배터리"])

    assert len(documents) == 1
    assert documents[0].url == "https://example.com/article"
    assert documents[0].content.startswith("실제 수집 본문")
    assert documents[0].reliability_tier == "official"


@pytest.mark.parametrize("validator", [telecom_validator, innovation_validator, planet_validator])
def test_sector_validators_drop_short_unattributed_and_duplicate_documents(validator):
    valid = SourceDocument(
        doc_id="valid", source_id="source", title="동일 제목", url="https://example.com/a",
        content="가" * 300, reliability_tier="official",
    )
    duplicate = SourceDocument(
        doc_id="duplicate", source_id="other", title="  동일   제목 ", url="https://example.com/b",
        content="나" * 300, reliability_tier="analyst_media",
    )
    short = SourceDocument(
        doc_id="short", source_id="source", title="짧음", url="https://example.com/c", content="짧음",
    )
    unattributed = SourceDocument(doc_id="none", source_id="", title="출처 없음", content="다" * 300)

    assert validator.validate([valid, duplicate, short, unattributed]) == [valid]


@pytest.mark.parametrize(
    ("analyzer", "env_name"),
    [
        (telecom_analyzer, "TRENDSPARC_SK_TELECOM_ANALYZER_API_KEY"),
        (innovation_analyzer, "TRENDSPARC_SK_INNOVATION_ANALYZER_API_KEY"),
        (planet_analyzer, "TRENDSPARC_SK_PLANET_ANALYZER_API_KEY"),
    ],
)
def test_sector_analyzers_never_fabricate_without_api_response(monkeypatch, analyzer, env_name):
    monkeypatch.delenv(env_name, raising=False)
    document = SourceDocument(
        doc_id="doc", source_id="source", title="기사", url="https://example.com/a", content="본문" * 100,
    )

    with pytest.raises(PipelineStageError):
        analyzer.analyze([document], "질문")
