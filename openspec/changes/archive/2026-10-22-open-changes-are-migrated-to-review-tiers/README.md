# open-changes-are-migrated-to-review-tiers

Phase 8 of the risk-tiered review work (design: `docs/risk-tiered-review-design.md`, philosophy:
`docs/agent-efficient-coding-philosophy.md`, both in the framework repo). Open changes were planned once, under one ceiling and with
no review tier, and a plan is made again only when a change's `tasks.md` moves. This change lets a person find the plans that are
stale, see what a new plan would do before any of it is applied, replan the unstarted remainder of a few changes at a time, and
rewrite the old test-kind tags in open `tasks.md` files, so the large units and the review tiers reach work that is already queued.

The steps a person runs, and when, are in agent-build-kit's `docs/runbooks/migrate-to-risk-tiered-review.md`.
