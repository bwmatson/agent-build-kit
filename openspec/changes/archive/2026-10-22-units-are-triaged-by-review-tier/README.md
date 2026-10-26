# units-are-triaged-by-review-tier

Phase 3 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). The review tier a unit's verdict recorded now orders the
queue a person works through and decides who is interrupted: a label on the pull request, the order in `abk status` and the review
tab, a card only for the units that need one. The verdict record gains an outcome derived from the unit's history, and the clean-merge
rate and agreement rate are computed from it, counting only units whose pull request carried the review brief. `abk review report`
prints them and says when a class clears the gates. The verdict's history floor now reads that real history. Nothing here merges.
