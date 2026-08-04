"""Request-local source collection progress shared by every sector adapter."""

from __future__ import annotations

from contextvars import ContextVar, Token

from common.contracts import SourceCollectionEvent


_EVENTS: ContextVar[list[SourceCollectionEvent] | None] = ContextVar(
    "source_collection_events",
    default=None,
)


def bind_collection_events(events: list[SourceCollectionEvent]) -> Token:
    return _EVENTS.set(events)


def reset_collection_events(token: Token) -> None:
    _EVENTS.reset(token)


def emit_collection_event(
    source_name: str,
    source_index: int,
    source_total: int,
    status: str,
    *,
    document_count: int = 0,
    detail: str | None = None,
) -> None:
    events = _EVENTS.get()
    if events is None:
        return
    events.append(
        SourceCollectionEvent(
            source_name=source_name,
            source_index=source_index,
            source_total=source_total,
            status=status,
            document_count=document_count,
            detail=detail,
        )
    )
