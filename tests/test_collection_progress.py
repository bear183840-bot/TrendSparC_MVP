from common.contracts import SourceCollectionEvent
from reporting.dashboard_streamlit.collection_progress_view import latest_collection_events


def test_latest_collection_events_keeps_final_state_in_source_order():
    events = [
        SourceCollectionEvent(source_name="SK IR", source_index=2, source_total=2, status="started"),
        SourceCollectionEvent(source_name="네이버 뉴스", source_index=1, source_total=2, status="started"),
        SourceCollectionEvent(
            source_name="네이버 뉴스",
            source_index=1,
            source_total=2,
            status="completed",
            document_count=2,
        ),
        SourceCollectionEvent(
            source_name="SK IR",
            source_index=2,
            source_total=2,
            status="failed",
            detail="timeout",
        ),
    ]

    rows = latest_collection_events(events)

    assert [(row.source_name, row.status, row.document_count) for row in rows] == [
        ("네이버 뉴스", "completed", 2),
        ("SK IR", "failed", 0),
    ]
