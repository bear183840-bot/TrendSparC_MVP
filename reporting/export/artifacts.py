"""Persistent, request-id based downloads for the Streamlit sidebar."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from reporting.export.report_pdf import build_dashboard_pdf, build_report_pdf

ArtifactKind = Literal["dashboard_pdf", "report_pdf", "result_json"]
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "outputs"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_EXTENSIONS: dict[ArtifactKind, str] = {
    "dashboard_pdf": ".pdf",
    "report_pdf": ".pdf",
    "result_json": ".json",
}


def artifact_path(
    kind: ArtifactKind, request_id: str, output_root: Path = OUTPUT_ROOT
) -> Path:
    """A collision-resistant path that never uses question text as a folder."""
    if kind not in _EXTENSIONS:
        raise ValueError(f"unknown artifact kind: {kind}")
    if not _SAFE_REQUEST_ID.fullmatch(request_id or ""):
        raise ValueError("request_id contains unsafe path characters")
    return output_root / kind / f"{request_id}{_EXTENSIONS[kind]}"


def ensure_artifact(
    kind: ArtifactKind,
    result: Any,
    question: str,
    output_root: Path = OUTPUT_ROOT,
) -> Path:
    """Create one export from the already-finished result, then reuse it."""
    path = artifact_path(kind, result.request_id, output_root)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "dashboard_pdf":
        payload = build_dashboard_pdf(result, question)
    elif kind == "report_pdf":
        payload = build_report_pdf(result, question)
    else:
        payload = result.model_dump_json(indent=2, exclude_none=False).encode("utf-8")
    path.write_bytes(payload)
    return path
