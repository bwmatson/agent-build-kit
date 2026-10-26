# Proposal

## Why

The three scheduling limits are counted over the whole workspace, so the work of one project decides what any other may start.

- **One backlog fills the places.** `max_units_in_progress` counts every unit started and not finished in every repo
  (`pipeline/units.py` `start_room` and `ready_units`); with a limit of 9, six failed units and three running ones leave nothing for the
  other repos, whose own ready work waits behind a backlog it has nothing to do with.
- **The workers and the lane are shared the same way.** `max_concurrent_stacks` sizes the one build pool and the free-slot counts
  (`cli/pipeline.py` `run_round`, `run_pass`), and `max_concurrent_restacks` sizes the one restack lane (`build_restack_lane`).
- **The settings read as workspace-wide because they sit among them.** The block also holds sizes, depth caps, rounds and timeouts that
  are workspace-wide by nature; the three are the only ones whose meaning is "per place the work is done".
- **The place already exists.** A repo declares its projects (`repos.<name>.projects`, found by `abk init`, added by `abk project init`),
  but a unit knows only its repo, so nothing can be counted for a project.

## What changes

- **A unit has a project.** A group heading may write `[<repo>/<project>]`, the project being a path the repo declares; a heading with
  the plain repo tag belongs to the repo's root project. A project the repo does not declare is refused, listing the declared ones.
  The unit records its project; groups of different projects are never in one unit or joined.
- **`global_limits` and `project_limits`.** `limits` is renamed `global_limits`, with `limits:` accepted as a deprecated alias that
  `abk config` and `abk doctor` warn of (both keys together is an error). `project_limits` is a new root block holding
  `max_units_in_progress` (5), `max_concurrent_stacks` (4) and `max_concurrent_restacks` (2), configured once and applied to each
  project separately; the three are removed from `global_limits`, and one left there is an error that points at `project_limits`.
  No repo or project overrides it, and there is no total across projects.
- **Counted for each project.** Units in progress, build workers and restack lanes are counted for the pair of repo and project. A full
  project skips only its own ready units; a repo with one project behaves exactly as today.
- **Said where a person looks.** `abk status` prints one queue line for each full project, and names `<repo>/<project>` on the ready,
  failed and blocked lines of a repo with several. The graph page nests a subgraph for each project of a repo that has more than one
  and is unchanged for one that has one.
- **`abk config --migrate`.** Renames `limits:` and moves the three settings by editing the file's text, every other byte unchanged,
  one backup, a diff and a question unless `--yes`, and nothing to do on a second run.

## Impact

- Capabilities: `unit-projects` (new: the tag, the refusal, the unit's project, the planner and joins, where a project is named),
  `limits-config` (new: the two blocks, the alias, the refusal), `project-limits` (new: counting, workers, lanes),
  `unit-graph-page` (new), `config-migration` (new), and `unit-scheduling` and `unit-joining` (modified: the limit, the reports, the
  sample row, the tag change, the join rule).
- Code: `config.py`, `installation.py`, `pipeline/work_graph.py`, `pipeline/units.py`, `pipeline/planner.py`,
  `pipeline/unit_store.py` (no new field of its own: the record inherits `Unit`'s), `pipeline/restack_lane.py`, `pipeline/diagram.py`,
  `cli/pipeline.py`, `cli/config_cmd.py`, `cli/doctor.py`, `cli/project_cmd.py`, `init/scaffold.py` and the new `config_migrate.py`.
- Behaviour that stays: a workspace whose repos each have one project schedules as it did; every other setting of the old block keeps
  its name under the new one; `runtimes.<name>.limits` keeps its name; branch names, the join rules and the calibration kinds ignore
  the project.
- Migration: an abk.yaml written before this change loads (with the alias), except that the three settings in it must move, which
  `abk config --migrate` does.
- Not in this change: a limit set for one repo or project (recorded as a possible follow-on), a machine-wide total.
