## From `ui-chat-editing/1`

- `abk attach release` should also refuse a unit the store has as RUNNING (for example, paused for the usage window part-way through a node), as POST /discard does. Today it checks only the branch lock (cli/attach.py:26).
- agent_state shows any RUNNING unit with no branch lock and a cause other than USAGE as 'streaming' with 'A step is running'. A read-only/paused reason would be accurate there (serve/chat.py:545).
- src/agent_build_kit/cli/attach.py:26 — `abk attach release` checks only the branch lock. The page's discard also refuses a unit the store has as RUNNING (`Chat.running`). So the CLI still discards or commits in the worktree of a unit paused part-way through a node for the usage window, where no lock is held and the agent's half-done edits are in the tree.
- src/agent_build_kit/serve/chat.py:545 — A unit stored RUNNING whose cause is not USAGE and whose branch lock no process holds is shown as 'streaming' with 'A step is running'. One example is a unit whose tick died before resuming it.

## From `ui-chat-editing/2`

- test_the_live_tail_streams_a_commit_fix_turn_and_not_a_chat_turn in tests/serve/test_chat_turns.py checks the node filter, but it uses the fixture change `feature`, so it would also have passed under the old filename match. A variant where the change name has a `commit` segment (for example `fix-commit-hook`) and only a `chat`-node turn is written would pin the regression from 2.1. It should assert that no delta from that turn reaches the stream before a later commit turn does.

## From `ui-chat-editing/3`

- In agent.tsx, both `proceedDisabledReason` and the Composer's `disabledReason` treat an empty `composer.reason` as 'enabled'. If the server ever disables the composer without giving a reason, Proceed anyway stays clickable. Deriving disabled from `composer.enabled` alone, and passing the reason only for display, would close that gap for both.
- The planning session's reply appears only in the inline 'Planning session' panel. There is no way to continue that conversation or open it on the Sessions page. A later unit could add a continue box, or a deep link once Sessions can open a specific session.

## From `ui-chat-editing/4`

- The free-session lease still counts every dirty path in the planning checkout, not only the files under the change's own directory (round 1's optional 1.7). Before the next unit relies on that count, record in the change's design what a lease on the planning checkout owns: the change's directory, or a snapshot of the paths taken when the lease is taken.
- docs/architecture.md:1062 says 'Commit is per checkout' but not that a request naming both checkouts gets a 422. Add that half-sentence so the doc matches the endpoint (serve/chat.py:774).
- consequences.py keeps its own `_NEEDS = ^Needs:` regex, while `specification_text` uses `work_graph.NEEDS_LINE`. If the two ever disagree on what a Needs line is, a line could count as a plan change and as a needs change at once. Reusing `NEEDS_LINE` in `_needs` would keep them aligned.

## From `ui-chat-editing/5`

- The live Claude Code acceptance module (tests/integration/test_chat_editing_claude_code.py) has still not been run against a real agent by the builder: it collects five `[claude_code]` scenarios under `-m local_stack`. Run it once with `uv run pytest -m local_stack tests/integration/test_chat_editing_claude_code.py` before or after merge to confirm the acceptance holds end to end.
