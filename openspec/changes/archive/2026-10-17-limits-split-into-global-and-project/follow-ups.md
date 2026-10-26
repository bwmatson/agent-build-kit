## From `limits-split-into-global-and-project/1`

- cmd_tags (cli/pipeline.py:4042), _tag_warnings (cli/pipeline.py:4023) and attach.planning_gate (pipeline/attach.py:144) still each spell out the `repos=tuple(inst.repos), projects=declared_projects(inst.repos)` pair. The four validate_tasks sites now go through `_validated`. One accessor, for example on Installation or a sibling of `_validated` used by attach.py too, would keep all of these in step when the validator needs another input.

## From `limits-split-into-global-and-project/2`

- tests/pipeline/test_planner_project_check.py:47 — The check that the refusal names the unit's own project is `"." in message.replace("c/1", "")`. Any full stop left anywhere in the message satisfies it.
- CHANGELOG.md:16 — The project bullet under Unreleased does not yet say that groups of different projects of one repo now become separate units, or that a started unit whose group is re-tagged to another project is reported and not re-planned.
- docs/architecture.md:107 — "A **unit** is one PR's worth of task groups, in exactly one repo" is now incomplete. A unit is also in exactly one project of that repo, and the `Unit.project` field is new.

## From `limits-split-into-global-and-project/4`

- src/agent_build_kit/config.py:586 — The comment on `TestsConfig.tier2_schedule` still says `None follows limits.tier2_schedule`. The line above it was updated to `global_limits.tier2_unit_scope`.
- src/agent_build_kit/init/scaffold.py:380 — `fill_missing_environment` spells the old key as the literal "limits" instead of using `config.DEPRECATED_ROOT_KEY`, the constant this change added for the same name.

## From `limits-split-into-global-and-project/5`

- tests/test_config_project_limits.py:1 — Nothing tests that `WorkspaceConfig.model_validate` refuses a scheduling setting left in `global_limits` or `limits`. That refusal was added for [1.4]; today only the `load()` path is covered.

## From `limits-split-into-global-and-project/11`

- src/agent_build_kit/config_migrate.py:110 — A `project_limits` written as `~` or `{}` is refused ('not a mapping of settings' / 'flow-style'), though both mean an empty block the moved lines could fill.

## From `limits-split-into-global-and-project/6`

- The `max_concurrent_restacks` comment in config.py and the abk-pipeline skill text still say "across all repos". Groups 8 and 13 own those, so they should change the wording when they make the restack lane and the docs per project.
- The full-queue line in the status (cli/pipeline.py:1948) still calls start_room with no project, so it counts the units in progress across every project. Group 7, which wires the tick and status to per-project counting, should pass a project there or report each project.

## From `limits-split-into-global-and-project/8`

- test_drain_joins_the_threads_of_restacks_that_ended_before_it can still pass on the old drain(). The tail of a lane thread after `ended.set_result(None)` is short, so the thread may already have exited before the is_alive assertion runs. To make the race deterministic, a later unit could hold that tail open: for example, a done-callback on the lane's finished future that blocks on an event the test releases only after drain() is called.

## From `limits-split-into-global-and-project/13`

- docs/cli.md and abk-pipeline SKILL.md describe the per-project queue-full line as listing its own blocked and failed-waiting units. `_queue_full_by_project` (cli/pipeline.py:2148) appends these to the same line as `; N blocked not counted; N failed waiting not counted`, but SKILL.md lifecycle step 3 still says 'The line is followed by "N blocked not counted"', which suggests separate lines. One wording pass would make the two docs match the actual layout.


## From `limits-split-into-global-and-project` (recorded after the change was archived)

- src/agent_build_kit/config.py:586 — The comment on `TestsConfig.e2e_schedule` still says `None follows limits.e2e_schedule`. The line above it was updated to `global_limits.e2e_unit_scope`.
