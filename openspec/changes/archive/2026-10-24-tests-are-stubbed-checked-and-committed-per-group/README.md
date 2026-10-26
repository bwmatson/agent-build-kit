# tests-are-stubbed-checked-and-committed-per-group

Phase 5 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). The test step writes stubs so its tests pass lint, format and
types, fixes any failure of those itself before anything is committed, and the build commits a tests-then-implementation pair for
each task group instead of one pair for the whole unit. It is behind a setting, off until it has run for a while, then on. A later
change reuses a group's pair by cherry-picking it when a unit is split.
