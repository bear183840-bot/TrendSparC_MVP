"""Standardized per-stage failure model for the request pipeline.

Every pipeline stage either succeeds, reports itself as a not-yet-implemented
template, is skipped, or fails. On failure it must raise PipelineStageError so
the orchestrator can record exactly which stage failed and why.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class StageStatus(str, Enum):
    OK = "ok"
    TEMPLATE_ONLY = "template_only"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageTrace(BaseModel):
    stage: str
    status: StageStatus
    reason: Optional[str] = None
    detail: Optional[str] = None


class PipelineStageError(Exception):
    def __init__(self, stage: str, reason: str, detail: Optional[str] = None):
        self.stage = stage
        self.reason = reason
        self.detail = detail
        super().__init__(f"[{stage}] {reason}")
