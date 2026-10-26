# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` in the build tool's checkout (origin/main at `7c42abc5`). Paths are under
`src/agent_build_kit/`; line numbers are approximate to a few lines.

- **How a command is registered** (`cli/__init__.py`). `COMMAND_MODULES` lists the modules in help order; each exposes `register(sub)`, its
  parser sets `func` (called `func(args, installation)`) and `needs_installation`. `main` loads the installation first and returns 2 on a
  `ConfigError` unless the value is `"optional"`. `abk policy` (`cli/policy_cmd.py`) is the nested form: `sub.add_parser("policy")`, then
  `commands.add_parser("apply")` with `set_defaults(func=..., needs_installation="optional")`; `abk project init` (`cli/project_cmd.py`) and `abk config`
  follow the same shape. A `planning split` registers the same way, as a module `cli/planning_cmd.py` added to `COMMAND_MODULES`, with the
  default `needs_installation=True`: the source is the installation in force.
- **The unit store** (`pipeline/unit_store.py`). `UnitStore(path)` reads the whole file on every call and validates each record with
  `StoredUnit.model_validate` (a bad record raises `ValueError` naming the file). `_write` writes `{"units": [...]}` through `_record` (the
  default priority and empty `description` and timestamps are left out) and `atomic_write_text`, then calls `on_write`. Every writer is
  wrapped by `_exclusive` (`UnitStore.locked()` is `file_lock` on `<store>.lock`). `upsert(units)` takes plan shapes and keeps state of the
  records it already has: it cannot carry a record's state, history, branch or feedback across, so copying a record needs a new method. A
  record references: `id`, `change`, `repo`, `project` (`.` default, on `Unit` since the limits change group 2), `depends_on` (unit ids),
  `needs` (a subset of `depends_on`), `joined` (`Member(change, groups)` entries: other changes' groups the unit builds), `groups`,
  `branch` (`spec/<id>`, a branch in the code repo), `pr`, `run_log` (a file name under the state directory's run-log folder), `trace`, and
  the free text `feedback`, `guidance`, `predecessor_note`, `stack_refusal`, `description` and each `history` entry's `note`. `Unit.members()` and
  `carries(change)` already say which changes a unit builds. `StoredUnit.held_by`, `state` (`UnitState`: planned, running, in_review, merged,
  closed, failed, held, satisfied, unplanned) and `IN_FLIGHT = (RUNNING, IN_REVIEW)` classify what a person must settle first.
- **Repos and projects** (`config.py`). `WorkspaceConfig.repos` maps a key to `RepoConfig` (`path`, `slug`, `profile`, `projects: list[ProjectConfig]`,
  `consumes: list[str]`, `relationships` prose); a project is a `path` relative to the repo, `.` the root; `owning_project` picks the deepest
  project holding a path. `PlanningConfig` holds `state_dir` (`runs`), `specs_dir` (`openspec`), `worktree_root`. `Installation.state_dir`,
  `.specs_dir`, `.changes_dir` (`<root>/<specs_dir>/changes`) and `.tasks_files()` are the paths; `load_installation(config_path)` loads one.
- **The heading tag** (`pipeline/work_graph.py`). Group headings read `## N. [repo] [tier] [flag]? title`. The limits change group 1 (merged, commit
  `4a65c921`) widened the first tag to `[repo/project]`: `split_repo_tag(tag, repos)` returns the repo and project, the root project is the
  plain `[repo]` (never `[repo/.]`), a tag that is itself a declared repo's name stays that repo, and `validate_tasks(path, *, repos=None,
  projects=None)` returns the groups (`TaskGroup` has `number`, `repo`, `project`, `tier`, `flag`, `title`, ...) and the errors.
  `group_sections(text, groups)` cuts raw group sections. `Needs:` lines (`NEEDS_LINE`: `Needs: <change> group <n>`) name another change.
  `specification_text(text)` is what the plan record hashes. Group 2 of the limits change (merged, `e8139ef3`) added `Unit.project`; group 3 (merged,
  `d039bcf7`) made the planner read it. The remaining groups of that change (limits blocks, per-project counting) are not built and are not needed
  here: **`--project` therefore needs no `Needs:` line**, because the tag reading and the unit's `project` are on origin/main. A `--project`
  that names a path the repo does not declare is refused with the declared ones, the message `validate_tasks` uses.
- **The openspec layout** on disk: `<specs_dir>/<redacted>` (carries the `# abk-rules: vN` stamp, `scaffold.rules_version`), `<specs_dir>/changes/<change>/`
  (`proposal.md`, `design.md`, `tasks.md`, `specs/<capability>/spec.md`, possibly `README.md`, `.openspec.yaml`, lock files such as `tasks.md.lock`),
  `<specs_dir>/changes/archive/<date>-<change>/` (same contents; `pipeline/archive.py` finds one by the suffix `-<change>`), and
  `<specs_dir>/specs/<capability>/spec.md` (the main specs, folded in by `openspec archive`). A change's delta specs are the capability names
  under its own `specs/`.
- **What stays at the source, by design.** `<state_dir>/planned.json` is machine-local and safe to lose (`_planned_hashes`: a forgotten record costs one
  model call; each record is `{hash, attempts, ok}` with the hash `sha256(specification(tasks))`); `spec-snapshots/<unit>/`, the usage ledger,
  `prs-<repo>.json`, run logs, transcripts, tier 2 and flake files are runtime history keyed by unit, not by planning root. They are not copied.
  A plan record of a moved change is: it is written to the destination through `record_plans`, with the hash recomputed over the text
  as written there (so a scrubbed `tasks.md` is not planned again), and removed from the source through `update_plans` on `--remove`.
- **Config text edits.** `runtimes/policy_apply.py` edits by text: `_parse` finds the structure, `_lines` splits at newlines only, `_end` finds a node's last
  content line, `_step` the indent step, `_insert` splices lines (CRLF kept), the original is copied once to `<file>.abk-backup` (`BACKUP_SUFFIX`)
  and the write goes through a temporary file keeping the mode (`_replace`). It only adds. `init/scaffold.py`'s `add_project` is the second precedent: it finds
  a repo's block under `repos:` with `_key_line`, `_key_at`, `_block_end`, splices lines, and **checks that the new text parses to exactly the
  old document plus the entry before it writes**, raising `ScaffoldError` and leaving the file alone otherwise. This change needs both an
  insertion (the repo's block into the destination) and a removal (the block out of the source), so it uses the line helpers of those two
  and ends with the same parse-and-compare check. The helpers are private there; the builder imports them or moves them into one shared module as a pure move
  (the limits change's `config_migrate` group does the same and allows the same move; whichever lands first owns it).
- **What a destination installation is** (`init/scaffold.py` `write_planning_repo`): `abk.yaml`, `<specs_dir>/<redacted>` (stamped, from
  `render_openspec_config`), a state directory with `units.json` (`{"units": []}`), a `.gitignore`, a `CLAUDE.md` and skills. Split needs the first
  three and never creates them: a destination without them is refused with the command that makes it (`abk init <dir>`).
- **Scrub terms** (`cli/scrub.py`). `terms_for(installation, target=...)` derives the installation-identifying words from `abk.yaml` (the planning root's name, repo
  names, owners and checkout names, deploy-rule words, `verify.env` names) and skips a repo whose checkout is `target`. The public-content change
  (`planning-content-follows-the-public-rule`) extends it (home facts, a local `scrub.local` list, no root name when the root is the target) and adds
  the companion `scrub_text`. **Its tasks were not written when this change was; so the exact names of `scrub_text` and the module are UNVERIFIED**
  (see the last section). This change calls them through one seam, `split/scrubbing.py`, and owns nothing about which words count.
- **`abk redact-history`** (`cli/redact_history_cmd.py`) is the precedent for a store pass: copy to `.pre-redact`, rewrite under `UnitStore.locked()`, atomic write. A split
  with `--scrub` does not rewrite the source store, so it needs no such copy.

## Decisions

### Dry run is the default; `--apply` writes

`abk planning split ... --to <dir>` prints the plan and exits. `--apply` carries it out. `--remove` is meaningful only with `--apply` (without it the plan
says what it would remove). The plan's exit code is 0 when there is nothing it refuses, 1 when it lists a refusal (so a script can gate on a
dry run), 2 for a usage problem or an installation that does not load. A flag called `--dry-run` is accepted as the explicit spelling of the default; given
with `--apply` it is a usage problem. Alternative rejected: `--dry-run` the default with `--no-dry-run` to write; a positive `--apply` is what a person types on purpose.

### Selection is by the groups' tags, over the working tree

A change is read from `<source>/<specs_dir>/changes/<change>/tasks.md` as the file is on disk now (modified, untracked and deleted files all count as they
are; a change whose directory is partly deleted in the tree is read from what is there). Its groups are read with `validate_tasks` and each group's
`(repo, project)` is its side: **moved** when it is the selected repo (and, with `--project`, that project), **staying** otherwise. A change with
only moved groups is moved; only staying groups, left; both, **mixed**. A `tasks.md` that fails to read
(a heading error) is reported as **unreadable** and left. `--project <path>` selects groups of `repo/path`; without it every project of the repo
moves, `.` included. The path is normalised as `abk project init` does and is refused when the repo does not declare it.

Archive entries follow the change they are named for: the entry's own `tasks.md` is classified the same way. An entry with no `tasks.md` (some archived changes have
none) is **unclassified**: listed, never moved. Main specs follow the changes that wrote their deltas: a capability is **moved** when every change (active and
archive) with a delta directory of that name is moved and at least one exists; **shared** when moved and staying changes both have one; **unowned** when
none does (a spec nobody's delta touches). Shared and unowned specs stay and are listed; `--spec <capability>` (repeatable) names a capability to
move anyway, because who owns a spec nobody's delta touches is a decision for a person; naming one is how the source's other consumers are
kept informed. Nothing about a spec is copied twice: an existing capability in the destination that differs is a conflict (see the copy).

### Mixed changes: refused unless a side is named

A mixed change is listed with the repo and project of every group and which side it would have on each. Without `--allow-mixed` the run refuses (exit 1, nothing
written). `--allow-mixed source` keeps every mixed change in the source and moves the rest; `--allow-mixed destination` moves every mixed change whole,
all its groups, to the destination. The second is refused for a change whose groups tag a repo the destination does not declare, naming the repo, because the units of that
change could not be read there (`Installation.repo()` raises `KeyError` for a unit whose repo is missing). A mixed change's archive entries and specs follow
it. The value names a side, not a change, so one flag decides every mixed change; the plan lists them so a person sees what they decided.
Alternative rejected: a per-change list. The count in the first real use is one.

### What a unit is, and what blocks it

A unit moves with its change: a unit whose `members()` are all moved changes. A unit that carries both (a `joined` member of a staying change, or its
own change staying while it carries a moved one) is a **spanning unit** and an error naming it and both changes; nothing is written. A unit in `running`,
`in_review` or `held` is **in flight** and refused, listed with its state: it has a worktree, a branch and a thread that belong to the source's worktree root (whose
default is derived from the planning root's name) and moving the record would orphan them. A person settles them and runs the command again; `--allow-in-flight`
is not offered, because the worktree facts cannot be moved by this command. A `failed` unit with a branch or a pull request moves: its record is
history plus a way back, and the way back is a requeue the person makes in the destination. UNVERIFIED that a failed unit's session resumes from the destination (the
thread's location is the state directory's, not copied).

### The copy: new store methods, plain files, no overwrite

Units: `UnitStore.import_units(records, *, scrub=None)` is a new method, exclusive like the rest, that validates each record as `StoredUnit`, adds it with its
state, history, branch, pr and every other field kept, and writes through `_write` (so `on_write` fires and the format is the store's). A unit
already there that is equal is skipped; one that differs is a conflict, refused, naming the id. `UnitStore.remove_units(ids)` is the other new method:
exclusive, removes records and writes. Neither is `upsert`: that merges a plan and would reset state. The public-content change adds one exclusive rewrite
method for its store pass; if that exists when this is built, the two share the lock and write helper, not the surface.

Files: a moved directory is copied file by file. A destination file that exists and has the same bytes is left; one that differs is a conflict, refused,
listed, nothing written. Lock files (`*.lock`) are not copied. Modification times are not kept. The source's file mode is. With `--scrub` the compare is against the scrubbed text.

Plan records: for each moved change the destination's `planned.json` gets `{hash, attempts, ok}` through `record_plans`, the hash recomputed by
`sha256(specification_text(<destination tasks.md text>))` (the function the tick uses), `attempts` 0 and `ok` true when the source's record was ok, and
nothing when the source had none (the destination plans it, which is what a never-planned change does).

The unit records' `run_log` and `trace` are kept as written: the logs stay at the source. UNVERIFIED that every reader of `run_log` tolerates the
file's absence (`abk status`, the graph page, `abk report`); a test in group 2 proves it for the readers the builder finds.

### The dangling-edge check runs before any write

For every moved unit: each id in `depends_on` and `needs`, and each `Member.change` in `joined`, must be a moved unit/change or already present in the
destination store/changes. Otherwise it is an error: `unit <id> <field> names <target>, which is neither moved nor in the destination`, one line each,
all of them listed, exit 1. A `Needs: <change> group <n>` line in a moved `tasks.md` is the same check at the change level. The reverse is reported too: a
staying unit or change whose edge points at something moved (it would dangle in the source after `--remove`) is listed as a warning without `--remove` and an error with
it. A `needs` edge to a unit already in the destination is allowed: the check reads the destination store.

### Scrub: one seam, applied to text and to named fields only

`--scrub` passes every moved text file's contents, and the free-text fields of every moved record (`feedback`, `guidance`, `predecessor_note`,
`stack_refusal`, `description.*` strings, each history entry's `note`), through `scrub_text(text, terms)` with `terms = terms_for(source, target=<moved repo's checkout>)`.
Identifiers (`id`, `change`, `repo`, `branch`, `run_log`, `trace`, `state`, timestamps) are never scrubbed, since a changed id breaks every edge. It
touches only files under the change, archive and spec directories it copies and the records it imports; nothing in a code repo. The plan prints how many
files and records the scrub would change, and how many substitutions. A term that is the moved repo's own name is not a term (`terms_for` already skips a repo whose checkout is the target),
so the moved repo can still name itself. Without `--scrub` the text is copied byte for byte.

**Dependency on the public-content change.** `terms_for` exists today; `scrub_text` and the home-directory facts are that change's. Its tasks were not
written when this was, so no `Needs:` line can name its group. Built in the plan's order (that change first, this one after, priority 3), the seam
imports it. If it is not merged when this is built, the builder stops at group 2 and the planner's `Needs:` is added by a replan naming that change's group that adds `scrub_text`.
UNVERIFIED: the module and function names. The seam is one small module precisely so that is the only place to change.

### Config edits are text splices with a check

Destination: when `repos.<key>` is absent from the destination `abk.yaml`, the source's block for it (its lines, comments directly above it kept, indentation re-based to the
destination's step) is spliced in after the last repo block; `consumes:` entries of the block naming a repo the destination does not declare are left in the text
but the plan lists them (the load would refuse them; the person decides). When it is present it is left alone, and the plan says `already declared`. A new
`<file>.abk-backup` is made once, as `policy apply` does, before a write, and the write is atomic keeping the mode.

Source, only with `--apply --remove`: the repo's block is removed, and only when **nothing left in the source names it**: no remaining unit (`repo`), no remaining change or
archive entry with a group tagged for it (including the unclassified ones the plan could not read), and no other repo whose `consumes` lists it. When something does, the
entry is kept and the run prints `kept repo <key>: still named by <list>` and exits 1 after finishing the rest. `--project` never edits the source's repo entry.

Both edits end with the parse-and-compare check `add_project` does: the new text parses to the old document with the block added or removed, and
loads with the config loader; if not, nothing is written, not even a backup, and the file and key are named. A layout the helpers cannot follow
(flow style, an anchor, a merge key on the repo) is refused as `policy apply` refuses.

### `--remove` is after a verified copy and removes only what was moved

Order: preflight (everything above) → copy to the destination → **verify** (re-read each destination file and compare its bytes with what was to be written;
re-read the destination store and compare each imported record to the source's, after the scrub) → remove from the source: the moved change, archive and
spec directories, then the unit records (`remove_units`), the plan records (`update_plans`), then the config entry. A verification mismatch stops before
anything is removed. A run killed in the middle leaves a destination that is a superset and a source that is a subset, and the next run, being idempotent, finishes it.
It removes nothing else: not the ledger, not snapshots, not logs, not the other changes' files, not a directory that holds a file the copy did not (it removes the files it moved, then the
directory only when empty).

### Idempotent, and the source is read-only unless `--remove`

Every step is a "make the destination equal to X" over what is read: a second run finds files equal, records equal, the entry declared, and the plan reads `nothing to do`
with counts of zero and exit 0. Without `--remove` the source is never written: no backup, no lock file created, no `.pre-redact`. (The source store is read through `UnitStore.all()`, which
takes no lock.) Neither repo is committed to; the report ends with the destination's `git status` summary line and the reminder to commit there.

### Output

The plan, in order: the source and destination; `selected: repo <key>[/<project>]`; one line per kind with counts (`changes`, `archive entries`, `specs`, `units`, `plan
records`, `config entries`); the refusals each as a line with its kind; the uncommitted files read (`git status --porcelain` of the source for the
paths under `<specs_dir>` and `<state_dir>`, as `M path` / `?? path` / `D path`, with a count); the scrub counts; and the last line, `dry run: nothing written. Add --apply.`
or the applied counts. A missing git repo (the source is not under git) says so and lists no uncommitted files.

## Pending changes read, and what was done with them

Checked: every change whose tasks mention `unit_store`, `policy_apply` or `docs/cli.md`. `limits-split-into-global-and-project` group 11 adds `config_migrate.py`
using the same private helpers (see above): whoever lands first may move them; the other imports from the shared module. `planning-content-follows-the-public-rule`
adds one exclusive rewrite method to `pipeline/unit_store.py` and `scrub_text`: this change adds two other methods in the same file; no shared lines. The planning-in-the-working-copy change was not
written when this was; it edits the paths a planning root is made of (UNVERIFIED that nothing there changes where `changes/`, `specs/` or the state directory are read from).
No `Needs:` between this change's own groups, none onto another change's group (reasons above).

## UNVERIFIED

- The names of `scrub_text` and its module in the public-content change (not written yet).
- That every reader of a unit's `run_log` and `trace` tolerates a missing file.
- That a failed unit's session can resume in the destination.
- That nothing in the planning-in-the-working-copy change moves where the specs and the state directory are read from.
- That a repo key never contains a `/`, so the first tag splitting `repo/project` is unambiguous (`split_repo_tag` asks the declared repos first, so a key with a slash still works).
- The mixed-change count and the number of unclassified archive entries in any real planning repo: the design reads them from what the command prints, not from a count made here.
