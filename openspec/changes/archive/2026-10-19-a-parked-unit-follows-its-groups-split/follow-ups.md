## From `a-parked-unit-follows-its-groups-split/1`

- src/agent_build_kit/cli/pipeline.py:2188 — When `resume_thread` raises inside the thread, it records the unit as failed and returns `Resumed(raised=True)`. `release_split_changed` treats that like a successful delivery: it still clears the park, moves the stored split to the new one and logs `reworking …`.
- src/agent_build_kit/cli/pipeline.py:2268 — The status wording for a moved unit whose new split is not held (`its group now says Split X, reworks this round`) has no test. The status tests cover only the held case and the unchanged case.
- src/agent_build_kit/cli/pipeline.py:2214 — Each tick calls `split_changes` twice, once in `release_split_changed` and again in `_releasable_split_units`. Each call re-reads and re-validates `tasks.md` for every parked unit, and the dry run and `abk status` repeat that work.
