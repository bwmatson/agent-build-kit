# low-risk-units-land-without-a-person

Phase 4 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). The first change that merges without a person: pipeline
code, never the build agent, squash-merges a unit whose verdict is `auto` and whose class a person has listed in
`review.auto_land.classes`, once the pull request's checks are green, and records it as merged through the path a person's merge
takes. Nothing is enabled by default and an empty list is the off switch. A sampled share of what lands is put to a person afterwards,
a digest says what landed, and a class that is reverted, fails verify or an audit, or stops agreeing with people is demoted
automatically by a runtime override that only a person lifts.
