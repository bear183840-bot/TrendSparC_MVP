# Unassigned Affiliate (name TBD) sector

Status: `template_only`.

This sector currently has no real collection, processing, validation,
analysis, or reporting logic. Every function under `adapter/` raises a
`PipelineStageError` explaining that it is not implemented yet. Do not add
fake/simulated data here — implement the adapter for real once source access
and analysis prompts for this sector are confirmed.

See `profile.json` for routing metadata (aliases/keywords used by
`core/sector_router`) and `prompts/system_prompt.md` for the (currently
empty) sector-specific system prompt template.
