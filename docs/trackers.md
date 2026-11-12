# Work trackers

A repo can mirror its changes onto a work tracker board: Azure DevOps or GitHub. The kit
writes the board from the specs and reads back what people do there. A repo with no
`tracker` section is not mirrored and nothing below applies to it. To turn it on, follow
`docs/runbooks/turn-on-a-tracker.md`.

## Configuration

The `tracker` section of a repo's entry in `abk.yaml` says how the board is shaped.

```yaml
tracker:
  kind: azure_devops
  levels: [change, group]      # any ordered subset of change, group, task
  epic: true                   # a person-made item above the first level
  pr_links: lowest             # lowest, all, or a list of levels
  create_cap: 50
  azure_devops:
    organization: example-org
    project: Example Project
    team: Example Team
    area_path: Example Project\Example Team
    iteration_path: Example Project\Sprint 1
    process: basic             # basic, agile, scrum or cmmi
    types:
      epic: Epic
      change: Issue
      group: Task
    states:
      new: To Do
      active: Doing
      done: Done
```

```yaml
tracker:
  kind: github
  levels: [change, group, task]
  pr_links: all
  github:
    owner: example
    repo: platform
    types:
      change: feature
      group: story
      task: task
```

- `levels` are the kit entities that become board items, outermost first: `change`, `group`
  and `task`, in that order, any subset. A Basic Azure DevOps board takes `[change, group]`
  (Issue and Task); Agile, Scrum and CMMI name User Story, Product Backlog Item or
  Requirement for a level.
- `types` gives the board type of each level in use, and of `epic` when it is set. Every level
  needs a type and no two levels share one.
- `epic` allows a person-made item above the first level. A change opts in with an
  `Epic: <id or exact title>` line above its first group in `tasks.md`; the kit only reads
  that item, never writes it.
- `pr_links` says which levels get a merged unit's pull request: `lowest` (the default),
  `all`, or a list of levels.
- `azure_devops:` holds the connection (`organization`, `project`, `team`, `area_path`,
  `iteration_path`), `process`, `types`, `states` and `states_by_type`. `github:` holds `owner`,
  `repo`, `host`, `project_number`, `types` and `states`.
- `token_env` names the environment variable of the credential, never the credential.
- The old flat keys are still read as the three levels and warn, and release 0.3.0 drops
  them: `story_type` (old), `labels`, `state_map` and the connection keys directly under
  `tracker`. A section cannot mix them with a provider block.

## Hierarchy

Each item hangs under the level above it in `levels`; the first level hangs under the epic
when one is set. The ids are kept in the change's `tracker.yaml`. A person-made item is
adopted with `abk tracker link`: `abk tracker link <change> <id>` for the change level,
`abk tracker link <change> <id> --group <n>` for a group, and `abk tracker link <change> --epic`
to record the change's `Epic:` item. A task item cannot be linked by hand, because tasks are
tied to lines of `tasks.md`.

## Ownership

The kit owns the items it created, marked by `marker_prefix`; a person owns an item they
made. The kit keeps the state, tags and children of an adopted item up to date and leaves
its title and body alone. A person assigned to a group or task item holds the units that
build it: the start check skips them until the item is cleared.

## Two-way rules

The spec is the source for structure and text: titles, task lines and which items exist.
The board is the source for state and assignment: a task marked done on the board ticks its
box, and a reopened one unticks it. Where the board disagrees about text or structure, the
spec takes precedence and the difference is recorded as a conflict, listed by
`abk tracker conflicts`.

Removals are never applied. An item removed on the board is recorded as a conflict and the
spec stays as it is. A conflict is closed with `abk tracker conflicts --resolve <id>` once
the two sides agree.

## Commands

- `abk tracker status` shows the target, identity, counts, items waiting, last push and pull
  and open conflicts.
- `abk tracker sync` runs the push and then the pull once; `abk tracker sync --dry-run` lists
  the creates and writes nothing. The first pass of a repo announces a backfill and creates up
  to `create_cap` items.
- `abk tracker link` adopts an existing item, as above.
- `abk tracker conflicts` lists and resolves conflicts.

Every command takes `--json`, and prints that no tracker is configured for a repo without a
section.

## Turning it on and off

Turning it on is a configuration step, a person's, because a builder cannot edit
`abk.yaml`; the runbook lists it. Turning it off is removing the section (or `kind: none`):
the ids stay in `tracker.yaml`, and the board keeps what was made.

## Migration

A later move of a planning repo carries each change's `tracker.yaml` with its folder and the
unit records with their old `story` ids (read, no longer written); `abk planning split`
copies both. The machine-local snapshot is rebuilt by the next pass and is not copied. The
`tracker` section stays in the `abk.yaml` of the planning repo that keeps the mirrored repo's
specs. Compare `abk tracker status` before and after the move.
