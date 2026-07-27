# unassigned source registry

Empty placeholder. `sources.json` currently contains no registered
sources — `core/source_planner` reads this file and returns an explicit
`template_only` note in `SourcePlan.notes` when the list is empty. Do not
assign an arbitrary reliability tier to a source that hasn't been registered
here first.
