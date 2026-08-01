from datetime import datetime, timedelta, timezone

from common.contracts import SourceDocument
from sectors.sk_hynix.adapter.validator import validate


def test_validator_filters_short_or_unattributed_documents():
    valid = SourceDocument(doc_id="1", source_id="source", title="title", url="https://example.com", content="가" * 300)
    short = SourceDocument(doc_id="2", source_id="source", title="title", url="https://example.com/2", content="짧음")
    no_url = SourceDocument(doc_id="3", source_id="source", title="title", content="가" * 300)

    assert validate([valid, short, no_url]) == [valid]


def test_validator_rejects_stale_documents_but_keeps_undated_ones():
    stale = SourceDocument(
        doc_id="1", source_id="source", title="옛날 기사", url="https://example.com/old",
        content="가" * 300, published_at=datetime.now(timezone.utc) - timedelta(days=800),
    )
    fresh = SourceDocument(
        doc_id="2", source_id="source", title="최근 기사", url="https://example.com/new",
        content="나" * 300, published_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    undated = SourceDocument(
        doc_id="3", source_id="source", title="날짜 없는 기사", url="https://example.com/undated", content="다" * 300,
    )

    result = validate([stale, fresh, undated])

    assert stale not in result
    assert fresh in result
    assert undated in result


def test_validator_drops_cross_source_title_duplicates():
    original = SourceDocument(
        doc_id="1", source_id="전자신문", title="SK하이닉스 HBM4 양산", url="https://etnews.example.com/a", content="가" * 300,
    )
    syndicated = SourceDocument(
        doc_id="2", source_id="디일렉", title="  SK하이닉스   HBM4 양산  ", url="https://thelec.example.com/b", content="나" * 300,
    )

    result = validate([original, syndicated])

    assert len(result) == 1
    assert result[0].doc_id == "1"


def test_validator_caps_at_eight_and_prefers_official_sources():
    documents = []
    for i in range(10):
        documents.append(
            SourceDocument(
                doc_id=str(i),
                source_id="source",
                title=f"기사 제목 {i}",
                url=f"https://example.com/{i}",
                content=f"본문 {i} " * 100,
                reliability_tier="analyst_media" if i < 9 else "official",
            )
        )

    result = validate(documents)

    assert len(result) == 8
    assert any(doc.reliability_tier == "official" for doc in result)
