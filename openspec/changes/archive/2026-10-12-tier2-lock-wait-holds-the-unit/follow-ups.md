## From `tier2-lock-wait-holds-the-unit/2`

- src/agent_build_kit/pipeline/tier2.py:125 — On the free-lock branch, the stale line says `process <pid> is gone` without calling `process_alive`, even though the held branch a few lines below does check it.
- src/agent_build_kit/pipeline/tier2.py:113 — The status probe holds a shared lock for a moment. A unit that tries for the free lock in that moment fails one non-blocking attempt, which makes `stack_lock` call `on_wait` right away (`next_say = began`).
- tests/cli/test_status_tier2_holder.py:47 — The new tests build the lock path by hand as `workspace.state_dir / "tier2.lock"` (lines 47, 61, 76, 92, 107, 120), right beside the new `Installation.tier2_lock` accessor this branch adds for exactly that path.
- src/agent_build_kit/pipeline/tier2.py:128 — The 'held, but its process is gone' wording now exists twice in different forms: `lock_status_line` (line 128) and `_waiting_message` (line ~140). The design gives a single phrase for both.
