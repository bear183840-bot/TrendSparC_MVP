"""Small, sector-neutral safeguards for evidence-grounded analyzers.

These helpers intentionally exclude table parsing and metric-recovery regexes.
They only preserve verbatim evidence, split oversized documents, and ensure
display points continue to reference a verified claim.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


def normalize_quote(value: str) -> str:
    """Normalize extraction artifacts without loosening factual matching."""
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u00a0", " ").replace("\u00ad", "")
    value = re.sub(r"[\u200b-\u200d\u2060\ufeff]", "", value)
    value = re.sub(r"(?<=\w)-\s*\r?\n\s*(?=\w)", "", value)
    return " ".join(value.split())


def split_evidence_passages(content: str, *, max_chars: int = 1_600) -> list[dict[str, str]]:
    """Return bounded, verbatim passages with stable local identifiers."""
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", content) if block.strip()]
    passages: list[str] = []
    for block in blocks or ([content.strip()] if content.strip() else []):
        remaining = block
        while len(remaining) > max_chars:
            minimum = max_chars // 2
            boundary = max(
                remaining.rfind("\n", minimum, max_chars),
                remaining.rfind(". ", minimum, max_chars),
                remaining.rfind("? ", minimum, max_chars),
            )
            end = boundary + 1 if boundary >= minimum else max_chars
            passages.append(remaining[:end].strip())
            remaining = remaining[end:].strip()
        if remaining:
            passages.append(remaining)
    return [
        {"passage_id": f"P{index:03d}", "text": text}
        for index, text in enumerate(passages, 1)
    ]


def quote_is_verbatim(quote: str | None, text: str | None) -> bool:
    return bool(quote and text) and normalize_quote(quote) in normalize_quote(text)


def verify_claim_quotes(
    claims: Iterable[dict], passages: list[dict[str, str]], *, source_url: str | None = None
) -> tuple[list[dict], list[dict]]:
    """Keep only claims whose quote occurs in a named or discoverable passage.

    The second return value is the claims that need the caller's one allowed
    repair attempt.  This function never substitutes a plausible quote.
    """
    passage_by_id = {passage["passage_id"]: passage["text"] for passage in passages}
    verified: list[dict] = []
    failed: list[dict] = []
    seen: set[str] = set()
    for claim in claims:
        claim_id = claim.get("claim_id")
        if not claim_id or claim_id in seen:
            continue
        seen.add(claim_id)
        quote = claim.get("evidence_quote")
        passage_id = claim.get("evidence_passage_id")
        if passage_id and quote_is_verbatim(quote, passage_by_id.get(passage_id)):
            pass
        elif not passage_id:
            passage_id = next(
                (identifier for identifier, text in passage_by_id.items() if quote_is_verbatim(quote, text)),
                None,
            )
        else:
            passage_id = None
        if not passage_id:
            failed.append(claim)
            continue
        location = claim.get("evidence_location")
        verified.append({
            **claim,
            "evidence_passage_id": passage_id,
            "evidence_location": f"{passage_id} / {location}" if location else passage_id,
            "source_url": source_url,
        })
    return verified, failed


def filter_points_by_verified_claim(
    points: Iterable[dict], claims: Iterable[dict], *, claim_type: str
) -> list[dict]:
    """Keep metric/comparison points only when their cited claim survived."""
    valid_ids = {claim.get("claim_id") for claim in claims if claim.get("claim_type") == claim_type}
    return [point for point in points if point.get("evidence_claim_id") in valid_ids]


def split_content(content: str, *, max_chars: int = 12_000) -> list[str]:
    """Split long source text on paragraph boundaries without losing its tail."""
    if len(content) <= max_chars:
        return [content]
    chunks: list[str] = []
    remaining = content
    while len(remaining) > max_chars:
        boundary = remaining.rfind("\n\n", max_chars // 2, max_chars)
        if boundary < max_chars // 2:
            boundary = max_chars
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks
