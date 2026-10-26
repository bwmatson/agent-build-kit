## From `a-moved-base-is-checked-by-what-it-can-affect/1`

- `_default_tier1` in pipeline/events.py:1663 still builds `build_tier1()` without `log`, so a caller of `build_restack` that injects no `tier1` gets no `moved base:` line. Production always passes `tier1_of` (cli/pipeline.py:2983), so no operator sees this today. It is worth giving `build_restack` a `log` when a later unit (group 2) makes the scope change what runs.

## From `a-moved-base-is-checked-by-what-it-can-affect/2`

- The design's note that the last full test count is 'kept on the run state' should be corrected in the planning repo (task 2.7). The count is actually the per-unit `last_full` dict inside build_tier1. The builder cannot edit the planning repo, so a person needs to make this change.

## From `a-moved-base-is-checked-by-what-it-can-affect/3`

- In the graph tier1 node (nodes.py:1648) and the merge handler (events.py:1971), the failure output is always `found.flakes[0].output`. When several flakes are collected and only a later one belongs to the unit's own fix change, the agent is shown the wrong test's output. Use the output of the flake whose `on_flake` returned None.
