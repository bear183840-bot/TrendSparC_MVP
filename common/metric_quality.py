"""Presentation-safe metric dimensions.

Numeric values and provenance are never altered.  A point whose label is URL
debris or a copied prose sentence is omitted only from structured charts; its
grounded claim remains in the evidence/report layer.
"""

from __future__ import annotations

import re
from typing import Any


_DEBRIS_RE = re.compile(
    r"https?://|www\.|%2f|%3a|(?:^|[/.])(?:com|net|org|co\.kr)/|[a-f0-9]{24,}",
    re.IGNORECASE,
)


def clean_dimension(value: object, *, maximum: int) -> str:
    text = re.sub(r"[*_`#◆▲▶■]+", " ", str(value or ""))
    text = re.sub(r"^\s*\\?[-–—•·]+\s*", "", text)
    text = re.sub(r"^[^\]]{1,12}\]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \t:;|[]()")
    if not text or _DEBRIS_RE.search(text):
        return ""
    if len(text) > maximum or len(text.split()) > 10:
        return ""
    if re.search(r"(?:은|는|이|가|을|를)$", text):
        return ""
    if re.search(r"(?:부터|다가|했으며|했다|됐다|나타났다)$", text):
        return ""
    if re.search(r"\d(?:\.\d+)?\s*%(?:p)?\s*(?:은|는|이|가)", text):
        return ""
    return text


def display_metric_points(points: list[Any]) -> list[Any]:
    cleaned: list[Any] = []
    for point in points:
        label = clean_dimension(getattr(point, "label", ""), maximum=60)
        if not label:
            continue
        subject = clean_dimension(getattr(point, "subject", ""), maximum=40)
        cleaned.append(point.model_copy(update={"label": label, "subject": subject or None}))
    return cleaned
