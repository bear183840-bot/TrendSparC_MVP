"""Generic entity extraction shared across all sectors.

This is deliberately shallow (keyword/regex only) — it is shared
infrastructure, not sector-specific business logic. Sector adapters may layer
their own entity resolution on top via their own contracts, but the pipeline
always has this baseline available.
"""

from __future__ import annotations

import re

from common.contracts import EntityExtractionResult, UserRequest

_ORG_PATTERN = re.compile(r"[A-Z][A-Za-z]{2,}(?:\s[A-Z][A-Za-z]{2,})*|[가-힣]{2,}(?:전자|하이닉스|텔레콤|브로드밴드)")
_TECH_PATTERN = re.compile(r"\b(HBM|DRAM|NAND|EUV|5G|6G|AI|IoT)\b", re.IGNORECASE)


def extract_entities(request: UserRequest) -> EntityExtractionResult:
    question = request.question
    organizations = sorted(set(_ORG_PATTERN.findall(question)))
    technologies = sorted({m.upper() for m in _TECH_PATTERN.findall(question)})
    keywords = sorted(set(question.split()))
    return EntityExtractionResult(
        request_id=request.request_id,
        organizations=organizations,
        technologies=technologies,
        keywords=keywords,
    )
