"""KOFIC PDF report collection helpers.

KOFIC report pages do not expose their PDF files as simple static links.
The page calls ``fn_fileDownload(...)``, which then posts file parameters to
``/kofic/business/comm/file/downloadFile.do``. This module keeps that special
behavior isolated from sector adapters so the SK Broadband adapter can reuse it
later without embedding site-specific parsing logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

KOFIC_BASE_URL = "https://www.kofic.or.kr"
KOFIC_DOWNLOAD_ENDPOINT = f"{KOFIC_BASE_URL}/kofic/business/comm/file/downloadFile.do"
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class KoficAttachment:
    """PDF attachment parameters extracted from a KOFIC detail page."""

    attach_seq_number: str
    file_url: str
    file_name: str
    download_name: str


@dataclass(frozen=True)
class KoficParsedPdf:
    """Parsed KOFIC PDF payload ready for a sector adapter."""

    detail_url: str
    attachment: KoficAttachment
    markdown: str


_DOWNLOAD_PATTERN = re.compile(
    r"fn_fileDownload\(\s*"
    r"'(?P<attach_seq_number>[^']+)'\s*,\s*"
    r"'(?P<file_url>[^']+)'\s*,\s*"
    r"'(?P<file_name>[^']+)'\s*,\s*"
    r"'(?P<download_name>[^']+)'\s*"
    r"\)",
    re.IGNORECASE,
)


def extract_pdf_attachments(html: str) -> list[KoficAttachment]:
    """Extract PDF attachment download parameters from KOFIC HTML."""

    attachments: list[KoficAttachment] = []
    for match in _DOWNLOAD_PATTERN.finditer(html):
        download_name = match.group("download_name").strip()
        file_name = match.group("file_name").strip()
        if not download_name.lower().endswith(".pdf") and not file_name.lower().endswith(".pdf"):
            continue
        attachments.append(
            KoficAttachment(
                attach_seq_number=match.group("attach_seq_number").strip(),
                file_url=match.group("file_url").strip(),
                file_name=file_name,
                download_name=download_name,
            )
        )
    return attachments


def fetch_detail_html(detail_url: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """Download a KOFIC detail page as text."""

    response = requests.get(
        detail_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def download_pdf_bytes(
    attachment: KoficAttachment,
    referer_url: Optional[str] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    """Download a KOFIC PDF through the official POST endpoint."""

    response = requests.post(
        KOFIC_DOWNLOAD_ENDPOINT,
        data={
            "fileUrl": attachment.file_url,
            "fileNm": attachment.file_name,
            "dnFileName": attachment.download_name,
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            **({"Referer": referer_url} if referer_url else {}),
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"%PDF-"):
        raise ValueError("KOFIC download response is not a PDF file.")
    return content


def parse_pdf_with_firecrawl(
    pdf_bytes: bytes,
    api_key: str,
    filename: str = "kofic_report.pdf",
    timeout_seconds: int = 120,
) -> str:
    """Parse downloaded KOFIC PDF bytes into markdown using Firecrawl."""

    from firecrawl import Firecrawl  # imported lazily so unit tests do not need network/API setup

    client = Firecrawl(api_key=api_key, timeout=timeout_seconds, max_retries=1)
    document = client.parse(pdf_bytes, filename=filename, content_type="application/pdf")
    data = document.model_dump() if hasattr(document, "model_dump") else document.__dict__
    markdown = data.get("markdown") or ""
    if not markdown.strip():
        raise ValueError("Firecrawl did not return markdown for the KOFIC PDF.")
    return markdown


def collect_pdf_markdown_from_detail_url(
    detail_url: str,
    firecrawl_api_key: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> KoficParsedPdf:
    """Fetch a KOFIC detail page, download its first PDF, and parse it with Firecrawl.

    This is intentionally detail-page based. A sector adapter may decide how to
    discover candidate KOFIC detail URLs, then call this function for each one.
    """

    html = fetch_detail_html(detail_url, timeout_seconds=timeout_seconds)
    attachments = extract_pdf_attachments(html)
    if not attachments:
        raise ValueError("No PDF attachment found in the KOFIC detail page.")

    attachment = attachments[0]
    pdf_bytes = download_pdf_bytes(
        attachment,
        referer_url=detail_url,
        timeout_seconds=timeout_seconds,
    )
    markdown = parse_pdf_with_firecrawl(
        pdf_bytes,
        api_key=firecrawl_api_key,
        filename=attachment.download_name,
    )
    return KoficParsedPdf(detail_url=detail_url, attachment=attachment, markdown=markdown)


def save_pdf(pdf_bytes: bytes, output_path: str | Path) -> Path:
    """Persist downloaded PDF bytes to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes)
    return path
