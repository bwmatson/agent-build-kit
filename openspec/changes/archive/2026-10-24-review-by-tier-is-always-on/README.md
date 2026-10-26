# review-by-tier-is-always-on

The last phase of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo), the cleanup that ends the build-out. The `review.enabled`
flag and the deprecated `global_limits.max_unit_lines` are removed so review by tier is simply how abk works, and the documents,
skills and wording stop saying a human merges every pull request. The reviewer's `needs_human` and `escalate` outputs are kept: they
are the way a reviewer hands a problem it cannot resolve to a person during review, which is a different thing from the tier it
classifies.
