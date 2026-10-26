# units-are-sized-by-review-tier

Phase 6 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). Adds a size ceiling for each review tier (`auto` 5000,
`light` 2000, `full` 750), deprecates `global_limits.max_unit_lines` in favour of the `full` one, teaches the planner and its plan
check to size a unit by the tier it is expected to get, keeps a group that expects full review out of a unit with lower-tier work,
and makes a plan record the configuration it was sized under, so a change of ceilings marks plans stale. All of it is dormant until
`review.enabled` is true: with it off, `max_unit_lines` alone governs and nothing is sized differently.
