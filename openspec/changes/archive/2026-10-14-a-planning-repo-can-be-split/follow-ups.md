## From `a-planning-repo-can-be-split/1`

- src/agent_build_kit/split/select.py:329 — When neither the specs directory nor the state directory is under the source root, `uncommitted` returns `()` without running git. The docstring says it returns None when the source is not under git, so in this case "nothing uncommitted" and "git was never asked" look the same.

## From `a-planning-repo-can-be-split/3`

- src/agent_build_kit/cli/planning_cmd.py:70 — The rework now builds the source config path as `source.root / CONFIG_FILENAME`. Before, it used `locate(args.config or settings.config)`, so a source loaded through `--config` or `ABK_CONFIG` pointing at a file with another name now has its repo entry read from a different file, or from a missing one.

## From `a-planning-repo-can-be-split/4`

- tests/split/test_remove.py:160 — The kill points are hard-coded as `range(1, 9)`, so the parametrisation only matches the plan's file count by coincidence with today's `populate` fixture.
