## From `unit-graph/1`

- Add a CHANGELOG entry covering the new langgraph, langgraph-checkpoint, langgraph-checkpoint-sqlite and aiosqlite dependencies, and `ABK_ENGINE`. Note that `graph` is not usable yet and that an unknown value is now refused when settings load.
- Re-wrap the `ABK_ENGINE` sentence in skills/abk-config/SKILL.md to match its paragraph.
- CHANGELOG.md:1 — The unit adds runtime dependencies (`langgraph`, `langgraph-checkpoint`, `langgraph-checkpoint-sqlite`, `aiosqlite`) and a new `ABK_ENGINE` setting. `ABK_ENGINE` is now a `Literal`, so an invalid value stops every command. CHANGELOG.md mentions none of this.
- src/agent_build_kit/skills/abk-config/SKILL.md:17 — The reworded sentence is no longer wrapped. Line 17 runs well past the width of the paragraph around it.

## From `unit-graph/2`

- docs/unit-graph.md: re-flow the closing sentences of the status paragraph (from 'and the only one that builds. This document is what the' onward) to the paragraph's wrap width.
- docs/unit-graph.md:26 — After the re-wrap, the line 'and the only one that builds. This document is what the' ends well short of the paragraph's width, so the next lines are still ragged.

## From `unit-graph/3`

- The PR description should say that on the spent-rounds path, a BaseMissing at open_pr now goes back through prepare with a fresh round budget. The classic `_spend_rounds` let the exception propagate instead. This difference is deliberate, and the builder said they have not written the description yet.
- The e2e-test gate prose in docs/unit-graph.md now runs past the paragraph's line width. Rewrapping it would keep the source readable.

## From `unit-graph/4`

- Add a graph-path assertion that a rework refused by `_deliver` (held, or a node to run) makes no fetch_review/fetch_checks call. Today only the classic-path claim refusal is pinned, by tests/pipeline/test_events.py::test_a_deferred_rework_fetches_nothing.
- tests/graph/test_graph_tick.py:285 — Nothing tests the graph-engine side of the lazy fetch. `test_a_comment_on_a_held_unit_waits_and_is_delivered_once_the_tick_has_run_it_back` polls twice while delivery is refused (held, then a node to run), but it never checks that no review or check fetch happened on those polls.

## From `unit-graph/5`

- docs/architecture.md:158 still says 'Reclaiming' happens at the start of a pass. Reword it to name converting units in flight.
- tests/graph/test_switch_tick.py: fix the two test names the rename broke, `test_a_tick__builds_a_unit_on_its_thread` and `test_a_unit_killed_mid_node_is_resumed_there_`.
- The PR description should list which deleted classic tests covered removed resume bookkeeping (checkpoint, record_step, reclaim_stale, the wip: commit) and so were not ported, as round 1 asked.
- docs/architecture.md:158 — 'Reclaiming, verifying and archiving also stay at the start of a pass' still names reclaiming, which no longer exists.
- tests/graph/test_switch_tick.py:72 — Removing the 'with no engine setting' suffix left two broken test names: `test_a_tick__builds_a_unit_on_its_thread` (double underscore) and `test_a_unit_killed_mid_node_is_resumed_there_` (trailing underscore).
## From `unit-graph/6`

- Before merging, someone with an agent on the host must run `uv run poe test-local-stack` once. The PR description should say whether `test_graph_acp_unit.py` passed. The builder could not run it: there was no <redacted> and the run bills on demand. 1.1 meant the old version could never have passed, so a green tier-2 run is still unproven.
- test_graph_acp_unit.py:52/265: ask for a unique token in COMMENT and assert that token, not any `"""`, so the check proves the review notes reached the rework agent.
- test_graph_acp_unit.py:232-255: replace the hand-written review/comment shapes with ones captured from a real `gh` response, with names neutralised.
- The PR description should say that the Testing section of `docs/unit-graph.md` already describes this acceptance test, so 6.2 left the doc unchanged.
- tests/integration/test_graph_acp_unit.py:265 — The new `'"""' in marker` check passes whether or not the rework read the comment, as long as the first build already wrote any docstring in marker.py. Agents often add a module or function docstring without being asked.
- tests/integration/test_graph_acp_unit.py:232 — The three fake shapes (`review`, `rest_review`, `rest_comment`) were written from memory, not copied from a live `gh` response. They carry the fields the code reads, but not the rest of what GitHub sends: `commit_id`, `diff_hunk`, `original_line`, `side`, `html_url`, `authorAssociation`, `commit.oid` and so on.
