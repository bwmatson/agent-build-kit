# review-policy-and-verdict-recorded-in-shadow

Phase 1 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). Adds the `review:` policy section of abk.yaml, the review
tier a planner estimates and a reviewer classifies, and a deterministic verdict that is computed and recorded for every unit. Nothing
acts on the verdict yet: the pipeline behaves as before. This is the shadow mode every later phase is calibrated from.
