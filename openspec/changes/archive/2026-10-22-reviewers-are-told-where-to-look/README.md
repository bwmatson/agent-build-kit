# reviewers-are-told-where-to-look

Phase 2 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). The review reply gains a ranked focus list and a
skippable list, the pipeline adds a list of what it already verified, and the pull request body opens with all three and the unit's
review tier, ahead of "Why". Commits gain a body that says why. Pull request text only: nothing here decides a state, a hold or a
merge. It ships before any change that alters who merges, because it helps every review that remains, and the verdict record's
`brief` flag it sets is what later calibration is counted from.
