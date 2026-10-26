# e2e-tests-before-merge-are-optional

Phase 9 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). Adds a setting that lets an installation, or one of its
repos, run a unit's e2e-test tier after the merge instead of before it. A unit then records its e2e result as `deferred`, `verify`
runs the live tests as it does today, and the review verdict does not count a deferred result as green.
