# Proposal

## Why

One planning repo can end up managing several repos, and then one of them is better off holding its own specs, unit store and config, or the
planning repo has to be cut in two. Today that is a hand copy: change directories, archive entries, a slice of `runs/units.json`, an edit of
two `abk.yaml` files. Each piece has a way to go quietly wrong. A unit record copied without the unit it `needs` leaves a dependency that
points at nothing. A change that tags groups for two repos is split in half. A `tasks.md` edited on the way in is planned again, because the
plan record keys on its text. A file that is only in the working tree, not in `HEAD`, is lost by anything that reads the commit. A repo entry
removed from the source configuration while a unit still names it makes that unit unreadable.

## What Changes

- **A new command, `abk planning split --repo <key> [--project <path>] --to <dir>`.** It selects every change whose groups are all tagged for the repo
  (and project), the archive entries of those changes, the main specs only those changes touch, the unit records of those changes, and their
  plan records; and it moves them into the installation at `<dir>`.
- **Dry run by default.** Without `--apply` it prints the plan: counts for each kind, what it would refuse and why, and the uncommitted files it
  read. `--apply` writes the destination.
- **Refuses what it cannot move whole.** A change that tags groups for more than one repo is reported and refused unless `--allow-mixed`
  names the side that keeps it. A unit that carries groups of a moved and a staying change, a unit still running, in review or held, a
  destination missing what the moved content needs, and any `needs`, `joined` or `depends_on` edge, or `Needs:` line, that would point at
  nothing, are errors that name what they found, before anything is written.
- **Scrubbing.** `--scrub` strips installation names and home paths from the moved text and from the free text of the moved unit records
  (feedback, guidance, history notes), through the term list and the text function the public-content change provides. It never touches a code repo.
- **Config edits by text.** The destination's `abk.yaml` gains the repo's entry when it has none, by splicing lines in as `abk policy apply` does;
  with `--remove` the source's entry is removed the same way, only when nothing left in the source names the repo.
- **`--remove`.** After a verified copy, removes from the source only what was moved: the directories, the unit and plan records.
- **Idempotent and read-mostly.** A second run changes nothing. The source is written only under `--remove`.
- **Docs.** The command's entry in `docs/cli.md`, the `abk-pipeline` skill, the changelog.

## Impact

- Capability: `planning-split` (new).
- agent-build-kit: a new `cli/planning_cmd.py` registered in `cli/__init__.py`, a new `split/` package (selection, copy, config edits), two
  methods on `pipeline/unit_store.py` (`import_units`, `remove_units`), `docs/cli.md`, the `abk-pipeline` skill's text, the changelog.
- Not in this change: moving history (commits stay with the old repo), moving run logs, usage ledger or spec snapshots, moving unit worktrees
  or branches, splitting one project of a repo out of the source's repo entry, creating the destination installation (`abk init` does that).
