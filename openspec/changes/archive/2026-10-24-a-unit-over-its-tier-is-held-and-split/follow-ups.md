## From `a-unit-over-its-tier-is-held-and-split/2`

- src/agent_build_kit/pipeline/verdict.py:166 — A driver that names several groups, such as `groups 2 and 3` or `groups 2, 3`, now gives only the first group. Separately, a file whose name is only digits and an extension, such as `1.py`, is read as a group number, because `\d+\b` matches before the dot.

## From `a-unit-over-its-tier-is-held-and-split/4`

- Until group 9's split step lands, a unit held by size (held_by size) has no automatic way out. It raises no card, and a person's requeue of it (as opposed to one held for a person) records no waiver, so the next review holds it again. That is acceptable while review.enabled defaults to false, but the later unit should make sure a size-held unit cannot sit unseen if the split step is disabled or keeps deferring.
- The stored split_request stays on a unit after a person waives its size. The later units that read it (the split step, the status) should either clear it on a waiver or ignore it when size_waived is set.
- src/agent_build_kit/cli/pipeline.py:6655 — The size waiver is written before the requeue is delivered. A requeue that then fails with BranchBusy (return 1, 'requeue it again once it has stopped') still leaves size_waived set.
- src/agent_build_kit/pipeline/unit_store.py:263 — StoredSplitRequest copies verdict.SplitRequest field for field, with the tiers stored as str. The copy is needed because verdict.py imports unit_store, so the store cannot import SplitRequest.
- src/agent_build_kit/graph/nodes.py:1803 — The hold note names the unbuffered ceiling ('over the full ceiling of 500'), but the unit is held only past the buffered ceiling (600).

## From `a-unit-over-its-tier-is-held-and-split/6`

- src/agent_build_kit/pipeline/run_log.py:65 — `run_log._unit_prefix` and `transcript._prefix`/`_id_prefix` are now one-line wrappers around `units.unit_file_prefix`, so callers could call it directly.

## From `a-unit-over-its-tier-is-held-and-split/8`

- src/agent_build_kit/pipeline/planner.py:1307 — The sentence 'Each piece holds a contiguous run of those groups, in order' is only in the drivers branch. A split with no driver gets 'Keep the groups in their order', but `_check_split_shape` holds it to the same contiguous-run rule.
- tests/pipeline/test_planner_pins_prompt.py:25 — The `per_tier_sizing` fixture here (`limits()` + `configure(enabled=True)`) repeats `tests/split_plan_support.py:use_per_tier_sizing`.

## From `a-unit-over-its-tier-is-held-and-split/10`

- has_work now counts every unit held by size with a split request as work. If such a unit's change has broken tags, or a live process holds its branch for a long time, every tick runs only to log 'not splitting' or 'waiting for its branch'. This is harmless, but such a unit could get a card or a backoff if it stays that way.

## From `a-unit-over-its-tier-is-held-and-split/13`

- No single test runs a real `split_held_units` and then prepares a piece through `build` from the ref it kept. The chain is covered in two halves that share one production function, `keep_superseded_tip`: tests/cli/test_split_keeps_branch.py and tests/graph/piece_fakes.py. One test across both steps would pin the handover.
- src/agent_build_kit/pipeline/workspaces.py:268 — `keep_superseded_branch` (the version that takes the lock) is now called only by tests/pipeline/test_superseded_branch_ref.py. Production code keeps the ref through `keep_superseded_tip` from inside the split step's own lock.
- src/agent_build_kit/cli/pipeline.py:2707 — `_keep_branch` runs after `plan_round`, so a held unit whose local branch is missing pays for a split-planning agent call on every tick. The split is then refused with no round counted, so this repeats forever.
