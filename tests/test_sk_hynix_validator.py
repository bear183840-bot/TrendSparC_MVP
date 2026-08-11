from datetime import datetime, timedelta, timezone

from common.contracts import SourceDocument, WebSearchContext
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


def test_validator_requires_date_for_today_question():
    dated = SourceDocument(doc_id="dated", source_id="source", title="today", url="https://example.com/dated", content="body " * 100, published_at=datetime.now(timezone.utc) - timedelta(days=1))
    undated = SourceDocument(doc_id="undated", source_id="source", title="undated", url="https://example.com/undated", content="body " * 100)
    context = WebSearchContext(question="오늘 SK hynix HBM 최신 뉴스", as_of_date="2026-08-11", report_purpose_id="current_status")

    assert validate([dated, undated], context) == [dated]


def test_validator_honors_explicit_historical_window():
    old = SourceDocument(doc_id="old", source_id="source", title="history", url="https://example.com/old", content="body " * 100, published_at=datetime(2021, 1, 1, tzinfo=timezone.utc))
    context = WebSearchContext(question="SK hynix의 과거 투자 배경", as_of_date="2026-08-11", report_purpose_id="future_business")

    assert validate([old], context) == [old]


def test_validator_uses_as_of_date_as_the_recency_reference():
    document = SourceDocument(doc_id="historic-current", source_id="source", title="2024", url="https://example.com/2024", content="body " * 100, published_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
    context = WebSearchContext(question="2024년 SK hynix 현황", as_of_date="2024-12-31", report_purpose_id="current_status")

    assert validate([document], context) == [document]
