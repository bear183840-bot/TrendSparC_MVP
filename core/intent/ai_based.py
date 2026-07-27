"""2nd-pass, AI-based intent refinement — interface only.

No API key is used or required by this scaffold. When one is configured later,
this function is the single place that should call out to an intent-analysis
model, using the rule-based result as a prior. Until then it must fall back
to the rule-based result untouched.
"""

from __future__ import annotations

import os

from common.contracts import IntentResult, UserRequest

_API_KEY_ENV_VAR = "TRENDSPARC_INTENT_AI_API_KEY"


def classify_intent_ai(request: UserRequest, rule_based_result: IntentResult) -> IntentResult:
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if not api_key:
        return rule_based_result.model_copy(
            update={
                "raw_signal": {
                    **(rule_based_result.raw_signal or {}),
                    "ai_based_note": "template_only: no API key configured, rule_based result used as-is",
                }
            }
        )
    raise NotImplementedError(
        "AI-based intent classification is not implemented in this scaffold."
    )
