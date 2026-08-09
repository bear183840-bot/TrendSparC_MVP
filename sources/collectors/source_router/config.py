"""Source Router runtime configuration.

Everything doc1 describes as a threshold or a stop-policy number lives here
as a plain field rather than a hardcoded constant deep in a function — doc2
§13's "configurable, not hardcoded business truth" point applies even though
this build otherwise treats doc2 as non-blocking guidance (see plan file).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRouterConfig:
    # Model overrides. None (default) lets each module resolve its own model
    # from its own env var — see planner.py/_solar.py/web_search.py. Set here
    # only to override without touching the environment (e.g. from a test or
    # a one-off script).
    planner_model: str | None = None
    search_model: str | None = None

    call_timeout_seconds: int = 30

    # doc1 §4's query-count guidance is prompt-level (told to the planner),
    # not enforced numerically — these are hard ceilings applied on top,
    # regardless of how many the planner returns.
    max_priority1_queries: int = 5
    max_priority2_queries: int = 3

    # doc1 §25/§27 stop policy. The loop always terminates within these
    # bounds, however the model behaves.
    max_gap_loop_iterations: int = 3
    max_sources_to_inspect: int = 3
    max_web_search_calls: int = 8

    # PDF size routing (doc1 §11). Token counts are estimated from character
    # count when no real tokenizer is available — see pdf_parser.py.
    pdf_small_max_tokens: int = 25_000
    pdf_large_max_tokens: int = 80_000
    pdf_chars_per_token_estimate: float = 2.2

    min_content_length: int = 250
    max_evidence_chars_for_coverage_check: int = 6_000
