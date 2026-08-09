"""Best-effort media-type detection for collected source documents."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

_PDF_SUFFIX_RE = re.compile(r"\.pdf(?:$|[?#&=])", re.IGNORECASE)
# Content-Disposition is not a URL. RFC 6266's usual form quotes the filename
# ('attachment; filename="report.pdf"'), so the URL pattern above misses it -
# `.pdf` is followed by a closing quote, not by end-of-string or a query
# separator. That miss is not cosmetic: it drops the caller through to the
# streaming GET fallback, fetching the whole file just to learn what the
# header already said.
_PDF_DISPOSITION_RE = re.compile(r"\.pdf(?:[\"';\s]|$)", re.IGNORECASE)
_MEDIA_TYPE_KEYS = ("content_type", "contentType", "mime_type", "mimeType", "media_type")
_HEADER_KEYS = ("headers", "response_headers", "responseHeaders")
_DOWNLOAD_PATH_TOKENS = ("download", "attachment", "export", "filedown")
_DOWNLOAD_QUERY_KEYS = {"file", "filename", "fileseq", "download", "attachment"}
_PROBE_TIMEOUT_SECONDS = 10


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, Mapping) else {}
    data = getattr(value, "__dict__", None)
    return data if isinstance(data, Mapping) else {}


def _normalized_media_type(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.split(";", 1)[0].strip().lower()


def _pdf_from_headers(headers: Mapping[str, Any]) -> str | None:
    lowered = {str(key).lower(): value for key, value in headers.items()}
    media_type = _normalized_media_type(lowered.get("content-type"))
    disposition = str(lowered.get("content-disposition") or "")
    if media_type == "application/pdf" or _PDF_DISPOSITION_RE.search(disposition):
        return "application/pdf"
    return media_type


def response_media_type(response: Any) -> str | None:
    """Read MIME hints from Firecrawl SDK objects or mapping responses."""
    candidates = [response]
    root = _mapping(response)
    for key in ("metadata", "data"):
        nested = root.get(key)
        if nested is not None:
            candidates.append(nested)
            nested_mapping = _mapping(nested)
            if key == "data" and nested_mapping.get("metadata") is not None:
                candidates.append(nested_mapping["metadata"])

    fallback: str | None = None
    for candidate in candidates:
        data = _mapping(candidate)
        for key in _MEDIA_TYPE_KEYS:
            media_type = _normalized_media_type(data.get(key))
            if media_type == "application/pdf":
                return media_type
            fallback = fallback or media_type
        for key in _HEADER_KEYS:
            headers = _mapping(data.get(key))
            if headers:
                media_type = _pdf_from_headers(headers)
                if media_type == "application/pdf":
                    return media_type
                fallback = fallback or media_type
    return fallback


def _looks_like_pdf_name(value: str | None) -> bool:
    return bool(value and _PDF_SUFFIX_RE.search(value.strip()))


def _looks_like_download_endpoint(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    path = parsed.path.lower()
    if any(token in path for token in _DOWNLOAD_PATH_TOKENS):
        return True
    query_keys = {key.lower() for key in parse_qs(parsed.query)}
    return bool(query_keys & _DOWNLOAD_QUERY_KEYS)


def _probe_download_headers(url: str) -> str | None:
    """Inspect headers without consuming the response body."""
    try:
        response = requests.head(
            url,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        detected = _pdf_from_headers(response.headers)
        if detected == "application/pdf" or _looks_like_pdf_name(response.url):
            return "application/pdf"
    except requests.RequestException:
        pass

    try:
        with requests.get(
            url,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=_PROBE_TIMEOUT_SECONDS,
            stream=True,
        ) as response:
            detected = _pdf_from_headers(response.headers)
            if detected == "application/pdf" or _looks_like_pdf_name(response.url):
                return "application/pdf"
            return detected
    except requests.RequestException:
        return None


def detect_document_media_type(
    url: str | None,
    title: str | None,
    response: Any = None,
) -> str | None:
    """Detect PDFs even when a direct-download URL has no file extension."""
    detected = response_media_type(response)
    if detected == "application/pdf":
        return detected
    if _looks_like_pdf_name(url) or _looks_like_pdf_name(title):
        return "application/pdf"
    if _looks_like_download_endpoint(url):
        probed = _probe_download_headers(url or "")
        if probed:
            return probed
    return detected
