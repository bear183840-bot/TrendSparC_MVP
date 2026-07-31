"""validator for the sk_innovation sector adapter.

Drops any SourceDocument that can't be attributed back to its source or
carries no substantial content — per the global rule that content with no
source attribution must not appear in analysis or synthesis output
(prompts/global_system_prompt.md, principle 2). Does not fetch or rewrite
content; only filters what the processor already normalized.
"""

from __future__ import annotations

from common.contracts import SourceDocument

_MIN_CONTENT_LENGTH = 200  # 최소 글자 수 기준 (200자 미만은 단순 안내문이나 오류 페이지일 가능성이 높음)


def _is_valid(document: SourceDocument) -> bool:
    if not document.source_id or not document.url:
        return False
    if not document.content or len(document.content) < _MIN_CONTENT_LENGTH:
        return False
    return True


def validate(source_documents: list[SourceDocument]) -> list[SourceDocument]:
    """수집/전처리된 SK이노베이션 문서 중 출처 정보가 명확하고 유의미한 정보량을 가진 문서만 검증합니다."""
    return [document for document in source_documents if _is_valid(document)]
