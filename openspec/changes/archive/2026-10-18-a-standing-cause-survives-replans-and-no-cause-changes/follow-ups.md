## From `a-standing-cause-survives-replans-and-no-cause-changes/4`

- src/agent_build_kit/skills/abk-pipeline/SKILL.md:100 — The `planned` row says "A replan keeps a unit's cause". A replan keeps only a standing cause. An event cause such as `requeued` reads as none after one (pinned by tests/pipeline/test_replan_keeps_standing_cause.py).
- src/agent_build_kit/cli/pipeline.py:764 — The `abk status` dependency-wait line now also shows for a planned unit that has a saved requeue but a cause other than `gated`. Nothing in tests/cli covers that new branch. This is already noted in the change's follow-ups.md.
