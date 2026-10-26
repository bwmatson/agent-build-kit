## From `open-changes-are-migrated-to-review-tiers/10`

- The parse-back check in `_rename_test_kind_keys` (`written != read_new_settings(old)`) is still not covered by any test. The builder could not find an input that gets past the earlier refusals. If no input can reach it, a comment saying it is a backstop would tell the next reader it is unreachable on purpose.

## From `open-changes-are-migrated-to-review-tiers/2`

- src/agent_build_kit/cli/pipeline.py:3894 — The comment 'A group a started unit carries must still be in tasks.md…' now sits above the `_without_planner` call. It describes only one of the four outcomes that call decides, and the tag-validation comment above it is separated from `_validated` in the same way.
- src/agent_build_kit/cli/pipeline.py:4031 — An ordinary failed planning attempt still records the current `sizing_digest()`. If a stale plan's units are still stored, a failed replan followed by an outage carries that current digest forward, and the stale line disappears.

## From `open-changes-are-migrated-to-review-tiers/4`

- src/agent_build_kit/cli/pipeline.py:5890 — apply_planned replaces the whole units.json and planned.json with the scratch copies and does not check that the real store still equals `outcome.before`.

## From `open-changes-are-migrated-to-review-tiers/6`

- test_the_real_pause_ends_when_the_planning_wrote_it_to_end_with_no_grace_added_again brackets the deadline between two real datetime.now() readings. It does not pin the exact value under the installed fake clock, which round 1 suggested. The bounds would still catch the grace being added twice, because that adds two minutes, so this is not a blocker. Pinning the exact value would make the test tighter.

## From `open-changes-are-migrated-to-review-tiers/8`

- src/agent_build_kit/cli/pipeline.py:5684 — The tasks.md write and the plan-record rehash are two separate steps, and nothing stops a tick from running between them. For a file that mixed the two spellings, a tick that reads planned.json after `atomic_write_bytes` and before `update_plans` sees the rewritten text against the old as-written hash, and plans the change again.
- tests/pipeline/test_work_graph_digest_mixed_spelling.py:62 — The lock test only records that the tasks.md lock is held at the moment of the write. Moving the read out of the `with file_lock(...)` block would still pass.
- tests/cli/test_tags_fix_refuses.py:88 — Task 7.2 says a rewrite whose parse differs in repo, flag, title, tasks or kind is refused. The test only makes the kind differ.

## From `open-changes-are-migrated-to-review-tiers/11`

- Nothing tests the migration order in the abk-pipeline skill (abk config --migrate, tags --fix --all, replan --stale --report, --stale --dry-run, --stale --limit, --accept-unplanned). A test like test_the_migration_section_gives_the_order, aimed at the skill text, would stop the skill and docs/cli.md from drifting apart. Separately, step 3 in docs/cli.md is now one long line and could be rewrapped to match the lines around it.
