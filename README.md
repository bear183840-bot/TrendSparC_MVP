# TrendSparC_MVP

Initial scaffold for TrendSparC, an AI Trend Intelligence platform used by SK
affiliate staff (SK hynix / SK Broadband / a third affiliate TBD). A
requester's question is analyzed for intent/entities/sector, routed to a
sector-specific data pipeline, synthesized sector-agnostically, and adapted
into a report for a target **audience** (external / practitioner / executive
/ management) — audience meaning who the report is shown to, not who asked
the question.

This is a structural scaffold only: contracts and orchestration are real and
tested; sector data collection/analysis is stub-only (`template_only`) by
design. See `docs/architecture.md` for the full pipeline diagram and design
principles (contract isolation, failure traceability).

## Sector status

| Sector | Status |
|---|---|
| sk_hynix | `template_only` |
| sk_broadband | `template_only` |
| unassigned (3rd affiliate, name TBD) | `template_only` |
| general (fallback for sector-unspecified questions) | `template_only` |

Adding or removing a folder under `sectors/` changes what `core/sector_router`
recognizes, with zero changes to any file under `core/`.

## Setup

```bash
cd TrendSparC_MVP
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run the dry-run pipeline

```bash
python main.py --question "SK하이닉스 HBM 시장 전망은?" --audience practitioner
python main.py --request-file examples/requests/sample_request.json
python main.py --question "..." --sector sk_totally_made_up   # -> unsupported
python main.py --question "..." --force-fail-stage intent     # -> forced failure trace
```

Each run prints the full per-stage `StageTrace` list plus every intermediate
contract object (`IntentResult`, `EntityExtractionResult`, `SectorRoute`,
`SourcePlan`, `TrendSynthesis`, `ReportPlan`, `AudienceAdaptation`,
`DynamicLayout`) as JSON.

## Tests

```bash
pytest
```

Covers: full dry-run trace with no failures, unsupported-sector routing,
dynamic sector registry (add/remove a `sectors/*` folder with no `core/`
changes), and forced per-stage failure tracing.

## What's intentionally not implemented yet

- Real data collection/analysis for any sector (`sectors/*/adapter/*` all
  raise a `template_only` `PipelineStageError`).
- The 2nd-pass AI-based intent classifier (`core/intent/ai_based.py` is an
  interface only; no API key is used or required).
- Real dashboard/HTML/PDF rendering (`reporting/*/renderer.py` all return a
  `template_only` message).
- Any scheduler, background polling, or periodic cache refresh — out of
  scope by design.
