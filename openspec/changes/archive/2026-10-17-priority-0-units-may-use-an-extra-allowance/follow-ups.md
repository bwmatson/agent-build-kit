## From `priority-0-units-may-use-an-extra-allowance/2`

- src/agent_build_kit/cli/pipeline.py:2059 — The workers a project gains for its owed units (`extra_workers=owed_by`) are counted for every owed unit, even one that `ready_units` will not admit. The worker slice also still decides with its own count rather than deciding the lane itself. So inside the owed unit's own project the two can still disagree about a priority-0 start.
- src/agent_build_kit/pipeline/emergency_lane.py:26 — `_record` now names its file by hashing `f"{key.repo}/{key.project}"` with sha256[:12], a second copy of the same expression in `restack_lane.record_path` (src/agent_build_kit/pipeline/restack_lane.py:200-201).

## From `priority-0-units-may-use-an-extra-allowance/3`

- tests/cli/test_status_queue_full_single.py:20 still builds the app-only repos by hand. It could use tests/emergency_lane_support.app_only_repos instead (this change did not add that copy). In test_a_restack_run_over_the_cap_is_not_a_use_of_the_lane, `f"{owed}"` can simply be `owed`.
