"""Shared, sector-neutral search-term construction for registered sources."""

from __future__ import annotations

from common.contracts import PlannedSource


_GENERIC_COMPARISON_TERMS = {"경쟁사", "타사", "다른 기업", "다른 회사", "competitor", "competitors"}


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def build_source_search_terms(source: PlannedSource, question_terms: list[str]) -> list[str]:
    """Return terms ordered for the vocabulary likely to exist on ``source``.

    The focal company's own official channel should be searched with the user's
    terms first. Competitor, regulator, market, media, and sentiment sources use
    registry topics first; otherwise a competitor domain is often searched for
    the focal company name and returns nothing. Topic/question overlap leads the
    list, followed by the remaining source vocabulary and original question
    context. No new term is invented here.
    """
    question = list(dict.fromkeys(term.strip() for term in question_terms if term.strip()))
    topics = list(dict.fromkeys(topic.strip() for topic in source.topics if topic.strip()))
    if not topics:
        return question
    if source.role in {"official", "search"}:
        # Keep the question-specific query first, but retain registry-owned
        # vocabulary as independent fallback queries. General search channels
        # must never push a generic topic such as "latest news" ahead of the
        # user's company + KPI pair.
        return list(dict.fromkeys([*question, *topics]))

    normalized_question = [
        _normalize(term)
        for term in question
        if _normalize(term) not in _GENERIC_COMPARISON_TERMS
    ]
    source_anchor = topics[:1]
    secondary_topics = topics[1:]
    overlapping = [
        topic
        for topic in secondary_topics
        if any(
            _normalize(topic) in question_term or question_term in _normalize(topic)
            for question_term in normalized_question
        )
    ]
    remaining_topics = [topic for topic in secondary_topics if topic not in overlapping]
    # Keep one source-specific anchor, then immediately pair it with the
    # question's core entity/topic. This avoids queries made only from a
    # source's broad registry vocabulary while the actual user subject is
    # pushed to the tail and never searched.
    return list(dict.fromkeys([*overlapping, *source_anchor, *question[:2], *remaining_topics, *question[2:]]))


def _evenly_spaced(values: list[str], limit: int) -> list[str]:
    if len(values) <= limit:
        return values
    if limit <= 1:
        return values[:limit]
    indexes = [round(index * (len(values) - 1) / (limit - 1)) for index in range(limit)]
    return [values[index] for index in dict.fromkeys(indexes)]


def build_search_queries(ordered_terms: list[str], max_terms: int = 5) -> list[str]:
    """Build bounded retries without dropping the tail of a long question.

    The first query samples the full ordered term list from beginning to end.
    Subsequent queries cover the front and tail independently before falling
    back to one anchor. This keeps later concepts such as risks/actions in play
    while still allowing progressively looser searches when an engine treats
    multi-term queries as AND conditions.
    """
    terms = list(dict.fromkeys(term.strip() for term in ordered_terms if term.strip()))
    if not terms:
        return []
    candidates = [
        terms[:2],
        terms[:3],
        _evenly_spaced(terms, max_terms),
        [*terms[:2], *terms[-2:]],
        terms[-3:],
        terms[:1],
    ]
    queries: list[str] = []
    for candidate in candidates:
        query = " ".join(dict.fromkeys(candidate))
        if query and query not in queries:
            queries.append(query)
    return queries
