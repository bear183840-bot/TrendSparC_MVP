# common source registry

Cross-sector shared sources — anything registered here is merged into
*every* sector's `SourcePlan` by `core/source_planner`, regardless of
`sector_id` (including sectors with no sector-specific sources of their
own, e.g. `general`). Use this for sources that are useful no matter which
business-unit sector a question routes to (e.g. a general news portal),
not for anything specific to one sector's business — sector-specific
sources still belong under `sources/registry/<sector_id>/`. Do not assign
an arbitrary reliability tier to a source that hasn't been registered here
first.
