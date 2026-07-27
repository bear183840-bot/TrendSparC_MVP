# Architecture

```text
UserRequest
  |- Intent Analyzer         -> IntentResult          (rule-based first pass, AI-based interface stub)
  |- Entity Extractor        -> EntityExtractionResult
  |- Sector Router           -> SectorRoute + SectorProfile
  `- Source Planner          -> SourcePlan
            |
            v
  Search -> Fetch -> Parse -> Normalize -> Validate     (owned by each sector's adapter)
            |
            v
       SourceDocument[]
            |
            v
      DocumentAnalysis[]                                (owned by each sector's adapter)
            |
            v
        TrendSynthesis                                  (sector-agnostic, common aggregation)
            |
            |- Report Planner       -> ReportPlan
            |- Audience Adapter     -> AudienceAdaptation  (driven by audience/profiles, never by audience name)
            `- Layout Generator     -> DynamicLayout
                        |
                        |- Streamlit dashboard
                        |- HTML
                        `- one-page PDF
```

## Design principles

1. **Contract isolation.** Every block boundary is a Pydantic model defined in
   `common/contracts.py` (or a sector-local re-export under
   `sectors/<id>/contracts/`). A sector or audience implementation can change
   internally without requiring changes anywhere else, as long as its
   contract shape is unchanged. No code branches on a literal sector or
   audience name — routing and adaptation always go through a registered
   profile (`sectors/*/profile.json`, `audience/profiles/*.md`).

2. **Failure traceability.** Every pipeline stage either succeeds, reports
   itself `template_only`, is `skipped`, or `fails` with a reason — see
   `common/errors.py` (`StageStatus`, `StageTrace`, `PipelineStageError`).
   `core/request_pipeline/pipeline.py` builds a full per-request trace so any
   failure can be attributed to an exact stage without reading application
   logs line-by-line.

## Current status

Every sector under `sectors/` is `template_only`: adapter stub functions
exist for `collector/processor/validator/analyzer/reporter`, but every one
of them raises `PipelineStageError` rather than returning fabricated data.
`core/sector_router` discovers sectors by scanning `sectors/*/profile.json`
at call time — adding or removing a sector folder changes routing without
any change to `core/`.
