# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` in the build tool's checkout (origin/main at `9ccd9a2d`). Paths are under
`src/agent_build_kit/`; line numbers are approximate to a few lines.

- **The config** (`config.py`). `LimitsConfig` (~371) holds the three settings with their comments ("across all repos"):
  `max_concurrent_stacks: int = 4`, `max_concurrent_restacks: Annotated[int, Field(ge=1)] = 2` (on `main`: the restack lane merged) and
  `max_units_in_progress: Annotated[int, Field(ge=1)] = 5`, among about thirty settings that are workspace-wide. `WorkspaceConfig.limits`
  (~836) is read at about 45 sites (`installation.py`, `cli/pipeline.py`, `graph/nodes.py`, `pipeline/{planner,wiring,environment,events,
  network_probe,tier2,unit_size,usage_allowances,usage_guard,vocabulary}.py`, `serve/chat.py`, `init/scaffold.py`) and in the tests. The
  schema is `extra="forbid"` (`Frozen`). `ProjectConfig` (~640: `path`, `languages`, `profile`; `.` is the root), `owning_project`
  (~659), `RepoConfig.projects` (~698, "every project found in the checkout, root first"). `runtimes.<name>.limits` is a different
  block (`ClaudeLimitsConfig`, ~242) and is not renamed. `load()` (~919) reads the YAML, validates, then checks the runtime, forges and
  infra.
- **`Installation`** (`installation.py` ~139-148): the properties `max_concurrent_stacks`, `max_concurrent_restacks` and
  `max_units_in_progress` read `config.limits`; they are the only readers of the three (plus `stack_depth_*` and `max_plan_attempts`, which stay).
- **The consumers** (`cli/pipeline.py`). `run_round`'s free count (~1406: `inst.max_concurrent_stacks - len(in_flight | held)`),
  `_evaluate_round` (~1714-1727: `cap = max_concurrent or inst.max_concurrent_stacks`, `ready_units(..., max_concurrent=cap +
  len(for_the_lane), max_units_in_progress=...)`, then `slots = cap - running` and `[:slots]`), `_queue_full_line` (~1734, one line from
  `start_room(units, limit)`), the build pool in `run_pass` (~2055: `max_workers=inst.max_concurrent_stacks`), `sample()` (~2089-2106:
  `free`, `limit=`, `cap=`), `_planned_wait` (~4519: `QUEUE_FULL` from `start_room`), `build_restack_lane` (~3024-3093:
  `RestackLane(inst.max_concurrent_restacks, ...)`). **`has_work` (~2868) reads no limit** and needs no change.
- **The count** (`pipeline/units.py`). `in_progress`, `uncounted`, `failed_waiting_units`, `_waits_for_room` decide per unit from the
  state and the graph. `start_room(graph, limit)` (~801) is `limit - count of in_progress units`, over the whole graph.
  `ready_units` (~843) returns early when `max_concurrent - running` is 0, computes one `room`, and walks the ordered ready units
  taking `slots` of them and spending `room` on each unit that has never started. `plan_units` (~195) splits on a change of
  `repo`; `Unit` (~113) has `repo` and no project; `base_of`, `depth_of`, `open_parents` and `waiting_on` compare `.repo` (same repo
  stacks, another repo waits for a merge). `StoredUnit` inherits `Unit`, `UnitStore._read` validates each record with
  `StoredUnit.model_validate`, and `upsert` copies `unit.model_dump(include=set(Unit.model_fields))`, so a new field with a default
  reads old records and is carried by the plan with no store code.
- **The restack lane** (`pipeline/restack_lane.py`). `RestackLane(cap, move=, claim=, owed=, stamp=, log=)` with `hand_over`,
  `scan`, `drain`, `finished`, `running`, `waiting`; `owed_units(inst, units)` finds the owed units over every repo. Nothing in the
  class knows a repo; one instance serves the pass.
- **The headings** (`pipeline/work_graph.py`). `GROUP_HEADING` (~75) reads `[<repo>] [<tier>] [<flag>]?` and `validate_tasks(path,
  *, repos=None)` (~188) refuses an unknown repo (`known_repos()` is the active workspace's keys when `repos` is not given), an unknown
  flag and an unknown tier, collecting every error. Callers: `cmd_tags` through `check_tags`, the planning path (`cli/pipeline.py`
  ~1090, ~2428, ~2584, ~3991), `pipeline/attach.py` (~144), `init/propose.py` (~240), `unrelated_parent_warnings`. **`abk check` itself
  (`cmd_check`) runs the OpenSpec validation and prints the tag *warnings* only; it does not report tag errors.** The repo tag is
  therefore refused today by `abk tags`, at planning, at attach and in `init`'s proposal check, not by `abk check`.
- **The planner** (`pipeline/planner.py`): `parse` reads `repo` and `tier` from the reply and refuses an unknown repo (~133),
  `_check_groups` (~299) refuses a unit whose group is tagged for another repo, `in_flight_item` (~573) shows the planner each unit's
  `repo`, the prompt states the repo rule (~481) and the join rule (~551), and `check_joins` (`pipeline/joins.py` ~96, ~121) compares
  `(repo, tier)` of a taken unit and of a taken group. `Kind(repo, tier, flag)` is the calibration kind (~235).
- **The tag-change report** (`cli/pipeline.py` ~2455-2475) compares a started unit's stored `repo`, `tier` and `flag` with its groups'.
- **The graph generator** (`pipeline/diagram.py`): `render_mermaid` (~97) draws one `subgraph <repo>` for each repo, sorted, units
  sorted by `(repo, id)`, a plain `-->` within a repo and a dashed `-.->` across; `render_markdown` writes the page and its legend.
  `docs/unit-graph.md` is the hand-written description of the unit's graph and names the three settings at ~91, ~92, ~373, ~597.
- **The status** (`cli/pipeline.py` `cmd_status` ~479-640): the queue line, the blocked, failed-waiting and second-parent lines, the
  ready queue (`_ready_queue_lines` ~1823) and the failed lines all print `({unit.repo})`.
- **`abk config`** (`cli/config_cmd.py`) is registered with the default `needs_installation=True`, so the command line loads the
  configuration before it runs; `--show` is the default mode and `--path` the other. `abk policy` commands register with
  `needs_installation="optional"` (`cli/__init__.py` `main` lets a `ConfigError` through for `"optional"`).
- **`abk project init`** (`cli/project_cmd.py`) registers a project through `init/scaffold.py` `add_project`, a comment-keeping splice,
  and prints `registered <path> (<profile>) in <repo>`.
- **`abk init`** (`init/scaffold.py` ~171, ~349-390) writes the generated-file patterns under a `limits` key, extending an existing
  block in place when it finds one.
- **The text edit** `abk policy apply` does (`runtimes/policy_apply.py`): `_parse` finds the structure, `_lines` splits at newlines only
  so the join is the text, `_end` finds a node's last content line, `_step` the indent step, `_insert` splices lines (CRLF kept), the
  original is copied once to `<file>.abk-backup` (`BACKUP_SUFFIX`) and the write goes through a temporary file keeping the mode. It
  only adds; this change also removes and renames lines, which that code does not.
- **The ledger sample** (`pipeline/spans.py` `Sample`: `running`, `in_review`, `blocked`, `queued`, `free_workers`, `limit`, `cap`) is read by
  `usage_report.py` (~1101: a sample is "full" when `running + in_review >= limit`).

## Decisions

### The heading tag is `[<repo>/<project>]`, the project being its `path`

`<project>` is exactly the `path` the repo declares (`web`, `services/api`), normalised as `abk project init` normalises it (no `./`, no
trailing `/`). The root project is `.` and is never written: a plain `[<repo>]` is the root project, and `[<repo>/.]` is refused so
there is one spelling. The first `/` divides the tag, because a repo's key is normally a plain name; but nothing in `config.py`
forbids a `/` in a repo key (UNVERIFIED that none exists elsewhere, for instance in the branch or worktree naming), so the reader first
asks whether the whole tag is a declared repo and only then splits. A declared repo `team/app` therefore keeps working as `[team/app]`.
A tag whose left side is not a declared repo gets the existing unknown-repo message with the declared repos, not a project message.
Alternatives rejected: `[repo:project]` (a colon reads as a different tier tag), a fourth bracket tag (the three-tag grammar and the
tier and flag positions would change for every existing heading), and project names other than paths (a second name to keep in step
with `abk project init`).

A repo with no declared project beyond its root (the list is empty, or holds only `.`) says "declares only its root project" in the
refusal. A repo whose list lacks `.` (for instance a monorepo whose projects are all in subfolders; `detect_projects` lists the
root only when it declares itself) still has a root project for untagged groups: `.` is always a valid, implicit project of every repo,
whether or not it is listed.

### `Unit.project` is a string with the root as `.`

`project: str = "."` on `Unit`. `.` is `ProjectConfig`'s own spelling of the root, so a unit's project can be compared with a declared
path without a special case, and a stored record with no key reads as the root. It is part of `Unit`, not `StoredUnit`, so the plan
carries it and `upsert`'s `model_dump(include=set(Unit.model_fields))` writes it with no change to the store. The calibration `Kind`
does not take the project: estimates are calibrated by repo, tier and flag, and splitting the samples further would starve each kind.
The branch name (`spec/<change>/<n>`) does not take it either.

A project key for counting is a small frozen model `ProjectKey(repo, project)`, hashable, so it keys
the dictionaries the counts group by. A unit of a repo or project the configuration no longer declares is its own key: it is counted
with limits like any other and never merged into the root.

### Counting is a grouping of what exists, not a new rule

`in_progress`, `blocked`, `uncounted` and `failed_waiting` decide about one unit and stay as they are. What changes is the denominator:
`start_room(graph, limit)` becomes the room of one project, and `ready_units` works each project's room and slots separately. The
dependency rules do not change: a dependency between two projects of one repo is a same-repo dependency (a stack may form across
projects of a repo), and a cross-repo one waits for a merge, as before. The units counted for a project are those whose key is its
key; the blocked and failed-waiting ones are uncounted in their own project's count.

`ready_units(graph, *, max_concurrent, depth_cap, max_units_in_progress, excluded)` keeps its signature and its integers, which now
mean "for each project". The early return when no slot is free becomes a skip of that project's units. `run_round` adds the units owed
a restack to the cap (`cap + len(for_the_lane)`); that addition is per project (a project's cap plus its own owed units), which needs
the cap to be a per-project value inside the function (a mapping or a callable); how it is passed is the builder's. The walk keeps its
single start order (handoff first, then the rest by start key); a unit of a full project is skipped and the next considered, which is
what "a full project skips only its own ready units" means.

### The pass's pool and slots

`run_pass`'s `ThreadPoolExecutor(max_workers=...)` is sized as the build cap times the number of projects the pass could build in (every
declared project of every repo, plus the project of every stored unit that is not declared); a thread is created only when a unit is
submitted, so the size is a ceiling and the per-project slot count in `_evaluate_round` is the only thing that limits what starts. The
free-worker count used to resume units (`run_round`) and `sample()`'s `free` are per project. This is the only place a sum appears
and it is a capacity, not a limit.

### The ledger row keeps one total, for reporting only

`Sample.limit`, `Sample.cap` and `Sample.free_workers` stay single integers so readers that do not know projects keep working. They
become totals over the projects that have a unit not yet merged, closed, satisfied or unplanned (the limit of a project is the same
setting, so the total is the setting times the number of such projects). `usage_report.py` reads `running + in_review >= limit` as
"the queue was full"; with a total it reads "every live project together was full", which is a coarser statement than before and not
a bug: UNVERIFIED how the report's idle-hours figure reads in practice with two live projects, and a per-project row is a possible
follow-on. The gauges `abk.slots.free` and `abk.slots.idle_with_ready` take the same totals.

### The restack lane is a collection of lanes

`RestackLane` is not changed in what it does: `RestackLanes` (in the same module) holds one lane for each project key, created on first
use with `project_limits.max_concurrent_restacks`, and routes `hand_over(unit)` and the scan by the unit's key. `running` and `waiting`
return the units of every lane, so the code that reads them (`lane_busy`, `owed`) is unchanged. `finished()` waits for the first of the
lanes' own futures (a `concurrent.futures.wait` over them) and is complete at once when no lane has work; `drain()` drains every lane. The
branch claim and the repository's turn are per repo already, so lanes of two projects of one repo still take the repo's turn only for
their git phases, as two restacks in one lane did.

**`a-restack-takes-no-slot-and-runs-when-seen` group 2 and this group.** That group (planned, not started) adds the usage gate in front
of the lane's resolver (`pipeline/restack_lane.py`), a lane record read by `cmd_status` and the graph page, the status line `restacks:
N running, M waiting`, two gauges and docs. It edits `restack_lane.py` and the lane's status, as group 8 does, but not the same lines:
the gate wraps the resolver callable inside a lane's run, the record and status read `running`/`waiting` (which `RestackLanes` keeps as
totals), and group 8 adds a class beside `RestackLane` and changes how `build_restack_lane` constructs it. No `Needs:` is added: neither
rewrites code the other creates (the lane itself is on `main`). If group 2 lands first, its lane record should key the lane by project
when there is more than one lane; if this lands first, group 2's record reads the totals. Either order works; the wording to carry into
group 2 if it is edited again is in the next section.

### `limits` is an alias by a before-validator, and the warning comes from the file

`WorkspaceConfig` gains a before-validator that renames a root `limits` to `global_limits`, refuses both keys together (naming both),
and refuses the three scheduling names under whichever of the two the file used, with the message of the requirement (the key as
written, `project_limits`, `abk config --migrate`). A validator cannot warn about what it renamed, so `config.deprecations(path)` reads the
file's top-level keys and returns the notices; `abk config` prints them to the error stream and `abk doctor` turns each into a `warn`
check. Nothing else reads the alias. The class stays `LimitsConfig` (renaming it would touch about thirty more lines of source and
tests and every pending change that names it, for no gain); `ProjectLimitsConfig` is new. The alias is removed in a later release, which
is a follow-on, not part of this change.

`Installation`'s three properties keep their names and now read `project_limits`; their docstrings say each is the limit of one
project. There is no per-project accessor because there is no per-project setting: one value, applied to each key.

### `abk config` must run when the configuration does not load

The refusal of 5 makes a file that still holds a moved setting unloadable, and `abk config --migrate` is what repairs it, so the command
cannot sit behind the installation load that every command has by default. `abk config` is registered `needs_installation="optional"`
(as `abk policy` is); `--show` then reports the load error itself and exits 2, `--path` needs only `locate`, and `--migrate` reads the
file. `--config` and `ABK_CONFIG` choose the file as everywhere.

### The migration is a text edit with a check, not a dump

`config_migrate.migrate(text)` finds, with the YAML parse, the root `limits` or `global_limits` block and the lines of the three keys,
then edits lines: the key line is renamed (a trailing comment kept), each moved key's lines (its own line, and the comment lines directly
above it, which are taken to be about it) are removed and added, in the file's own indent step and with the value text unchanged, to a
`project_limits:` block put straight after the global block's last content line (comments after it stay where they were, as `_end`
defines the node). It uses the line helpers of `policy_apply` (its lines, `_end`, `_step`, `_insert`) because that is the technique
`abk policy apply` was built and tested on; they are private there, so the builder either imports them or moves them to a shared
module as a pure move (no change in `policy_apply`'s behaviour or tests). Where no setting remains the block is written `global_limits:
{}`: an empty key would load as null and fail. The one thing `policy_apply` does not do is remove lines, so the check after the edit
matters: the new text is parsed and compared with the old document with the rename and move applied in memory, and loaded by the config
loader; if either differs nothing is written. A file it cannot follow (flow style, an anchor on a moved key, a multi-line value, a
`project_limits` that already holds the setting, several documents, both old and new keys) is refused with the file and the key, as
`abk policy apply` refuses, and nothing is written, not even a backup.

The command is `abk config --migrate [--yes] [--dry-run]`: diff, then a question, then the backup (once, `<file>.abk-backup`, never
overwritten), then the write through a temporary file keeping the mode, with exits 0 (written or nothing to do), 1 (declined, or no
terminal and no `--yes`) and 2 (refused). Running it on a file already on the new names says so and writes nothing. It
works on the file in force, so the migration of an installation's own abk.yaml is a person's command at the time the change is built,
not part of any group.

### Display

The queue line names the project (`<repo>` for the root project, `<repo>/<project>` otherwise) only when the workspace has more than one
project in all; with one it reads exactly as before, so a test written against the old line passes unchanged for a workspace of one
repo with one project. The other status lines name the project only for a repo that has several. The graph nests project subgraphs
for a repo with more than one project among those it declares and those of its units in view; the rule is by the repo, not by the
view, so a repo with two declared projects is drawn the same whether one project's units are in view or both. The root project's nested
subgraph is titled `.`. The ids of the nested subgraphs are made so they cannot clash with a repo's or a unit's.

## Pending changes read, and what was done with them

Unit states are read from `runs/units.json` (read only). The three settings are named with a `limits.` prefix, or bare, in these
changes. The rule used: a change that builds before this one (their `Priority:` is 1 or 2; this one is 3) is written for the names
it will meet at that time, so a `limits.<setting>` of a setting that stays is correct then and, through the alias, afterwards, and is
**not** edited. Text that would be false after this lands (a moved setting named under `limits.`) is edited only where its group has
not started, and written so that it is true in either order.

| Change | Units | What it says | Done |
|---|---|---|---|
| `a-restack-takes-no-slot-and-runs-when-seen` | 1 merged, 2 planned | `limits.max_concurrent_restacks` throughout; the lane, `restacks: N running, M waiting` | Group 2's tasks 2.10 (docs) and 2.11 (the `abk-config` skill's block) edited to name `max_concurrent_restacks` in `limits` or `project_limits` by where it is. Group 1's text (README, proposal, design, spec, tasks 1.x) is started and left; it reads `limits.max_concurrent_restacks`, which after this change reads `project_limits.max_concurrent_restacks`, one lane for each project. Wording if group 2 is edited again: "the lane of each project holds at most `project_limits.max_concurrent_restacks` restacks; the status line totals them" |
| `tier2-runs-on-a-schedule` | 1 merged, 2 in_review, 3 running, 4 planned | `limits.max_units_in_progress` (proposal, spec requirement "A scheduled unit is tracked as normal work", group 4's Done-when and task 4.2); `limits.tier2_schedule`, `limits.tier2_unit_scope`, `limits.tier2_base_runs` (stay) | Group 4's Done-when and 4.2 edited as above. Its proposal and its spec's two lines (a requirement and a scenario that group 4 builds, in a started change) are left; the wording they need is "counts against `max_units_in_progress`, for the scheduled unit's project" |
| `a-failed-unit-resumes-when-its-wait-ends` | none (not planned) | `limits.wait_end_requeue` (a new setting of the block that stays); bare `max_units_in_progress` and `max_concurrent_stacks` in design and 1.8 | Nothing to edit: the bare names are still true (the requeue is not held by the limit; it is the project's limit now). If built after this change its `limits.wait_end_requeue` is `global_limits.wait_end_requeue`, which the alias reads either way |
| `a-moved-base-is-checked-by-what-it-can-affect` | 1, 2 merged, 3 running | `limits.restack_check` (stays) | Started; left. Reads `global_limits.restack_check` afterwards |
| `a-pr-that-stays-conflicting-is-moved-again` | 1, 2 merged, 3 planned | `limits.max_review_rounds` (stays) | Left: the setting stays, and the alias reads it |
| `flaky-cleanup`, `policy-check-asks-the-agents-own-matcher` | planned | `limits.tier1_repeat_runs`; `limits.policy_oracle_seconds`, `limits.policy_probe_seconds` (stay; the second adds new ones) | Left: unstarted, but they build first and the settings stay; new settings they add to the block are read from `global_limits` through the alias with the warning until the migration is run |
| `tier2-failures-in-untouched-tests-are-fixed-once`, `tier2-waits-on-open-base-failure-fixes` | merged / held | `limits.tier2_base_runs`, `limits.tier1_repeat_runs`, `limits.tier2_unit_scope` (stay) | Started; left |
| `unit-graph` | all merged | the spec says a graph slot "takes no slot from `max_concurrent_stacks`" | Started; left. After this change it reads "from the project's `max_concurrent_stacks`" |
| the archive | n/a | many `limits.` mentions | Never edited |

None of these changes needs a `Needs:` on this one or the other way: they name settings, not the position of a setting in a file, and
the alias and the migration carry a file written for either spelling. The tests of started groups that build a configuration with
`limits=` are updated by group 4 here, since they are in the tree by then.

## Landing order

The refusal of a moved setting under `global_limits` or `limits` is in group 5 and `abk config --migrate` is in groups 11 and 12, so
between group 5 merging and group 12 merging an abk.yaml that still sets one of the three does not load. An installation that runs the
pipeline from the framework's `main` should migrate its file by hand first (two or three lines moved under a new `project_limits`
key) or run the pipeline from a checkout that is held back until group 12 merges. Reordering would not remove it: the command checks its
result with the loader, which needs the block. The groups are small and in sequence, so the gap is a few merges long.

## Not in this change

- A limit for one repo or one project that differs from the root's (`repos.<name>.project_limits` or a per-project entry): the
  settings are configured once and applied to each, as decided. A follow-on, recorded here.
- A machine-wide total of units in progress or workers: none is kept.
- Removing the `limits` alias, which is a later release.
- A per-project ledger sample row; the row keeps totals.
- `abk check` reporting tag errors: today it reports tag warnings only (see "What was checked"). A refused project is refused by `abk tags`
  and by every planning path, which is where a repo tag is refused; making `abk check` refuse tags is a separate change.

## UNVERIFIED

- That no code or document outside the places listed forbids or assumes a `/` in a repo key (the heading reader tries the whole tag first
  so a declared repo with one keeps working).
- How `usage_report.py`'s queue-full hours read with a total limit over several live projects.
- Whether `ThreadPoolExecutor` sized as cap times projects is acceptable for a workspace with very many projects; threads start only on
  submit, so only the ceiling is large.
- The exact count of source lines that read `config.limits` (about 45) and of test constructions; group 4's estimate rests on it.
- That `abk doctor`'s configuration check is the right place for the alias warning (it is a `warn` check, `Check(status="warn")`, next to
  `config`); the builder places it beside the existing configuration check.
- The sizes: each group is estimated at 260 to 340 raw lines (the planner scales by about 1.9 and refuses above 750 calibrated); groups
  4 and 11 are the likeliest to run over and may be split at their test/implementation seam.

## Direction note: the test kinds are being renamed

Added while this change is in flight; it changes nothing this change specifies. The two kinds of test, today `tier1` and `tier2`,
are being renamed `unit-test` and `e2e-test` so that "tier" can mean how much review a change gets (see the risk-tiered review
design in the framework repository). The change `test-kind-names-are-accepted-both-ways` adds the layer that reads both spellings,
and group 5 and the groups after it wait for it, so they are built with the new names available.

- Names this change's specs fix (a setting, a tag, a metric) are built as the specs write them. The rename carries them; do not
  rename them by hand and do not edit the spec.
- Anything this change is free to name (a helper, a fake, a test file, a local name) uses the new words.
- If a check rejects an old spelling in a directory the rename has already converted, rename that occurrence to the new spelling,
  keep the behaviour the spec describes, and say so in the commit message. A reviewer reads the new spelling as the same setting as
  the spec's old one.
