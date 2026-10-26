# Proposal

## Why

A change is planned once and again only when its `tasks.md` changes. That keeps a model call off every tick, but it leaves a person no way to ask
for a plan. Three things have needed one:

- **A stale dependency.** A `Needs:` line was changed in two changes. The pipeline re-linked their gates, but each unit's `depends_on` came from an
  earlier plan and the linking only ever adds edges, so a unit kept waiting on a unit it no longer needed. The plan is rebuilt only when the change's own
  file changes, and a `Needs:` edit in another change does not change it.
- **A change that gave up.** After the allowed number of failed attempts a change is skipped until its `tasks.md` changes, and the only way out is an
  edit that exists only to change the hash.
- **A plan made beside different neighbours.** A plan is made against the in-flight and planned units of other changes. When those change, the plan can be
  wrong (two units each waited on the other) and nothing prompts a new one.

## What Changes

- **`abk replan <change>...`** plans the named changes now: it drops their recorded plan, asks the planner for each, and links the `Needs:` lines, the two
  steps a tick performs, so the result is what the next tick would have produced.
- **Selectors:** `--all` for every active change, `--failed` for every change whose last plan failed or gave up. With none the command lists each change
  with the state of its plan.
- **`--forget`** only clears the records, makes no model call and leaves the planning to the next tick.
- **It says what changed:** the dependencies added and removed, units that became `unplanned`, joins dropped, and the units that had started and were
  left alone.
- **Started work is never touched:** a unit that is running, in review, failed, held, merged or satisfied keeps its state, branch, pull request and history.
- **The way out is named:** the message that a change gave up planning, and the status line for a failing plan, say to run `abk replan`.

## Impact

- agent-build-kit: `plan_all` (a selection and a forced mode, with a per-change result), a new `replan` command, the write of the recorded plans, the
  messages, `docs/cli.md`, the pipeline skill and `docs/architecture.md`.
