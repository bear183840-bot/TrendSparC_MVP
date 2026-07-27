"""reporter stub for the sk_broadband sector adapter.

Not implemented on purpose: this sector currently has status template_only.
No fake data may ever be returned from here — only a clearly-labeled
PipelineStageError so the orchestrator's stage trace shows exactly which
sector adapter stage was called and why it can't proceed yet.
"""

from __future__ import annotations

from common.errors import PipelineStageError


def report(report_plan, synthesis):
    raise PipelineStageError(
        stage="sectors.sk_broadband.adapter.reporter",
        reason="template_only: sector adapter not implemented",
    )
