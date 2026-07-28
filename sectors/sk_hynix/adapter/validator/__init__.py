"""validator for the sk_hynix sector adapter.

Drops any SourceDocument that can't be attributed back to its source or
carries no substantial content — per the global rule that content with no
source attribution must not appear in analysis or synthesis output
(prompts/global_system_prompt.md, principle 2). Does not fetch or rewrite
content; only filters what the processor already normalized.
"""

from __future__ import annotations

from common.contracts import SourceDocument

_MIN_CONTENT_LENGTH = 200  # below this a page is almost never a real article body


def _is_valid(document: SourceDocument) -> bool:
    if not document.source_id or not document.url:
        return False
    if not document.content or len(document.content) < _MIN_CONTENT_LENGTH:
        return False
    return True


def validate(source_documents: list[SourceDocument]) -> list[SourceDocument]:
    return [document for document in source_documents if _is_valid(document)]
