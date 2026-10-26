# Design

## Context

`plan_all` (`cli/pipeline.py`) plans a change when its `tasks.md` digest differs from the one in `runs/planned.json`, or when its last
plan failed and attempts remain, or when `abk replan` forces it. It asks the planner once per change (none when every group is already
taken by a started unit or another change's planned unit), then `UnitStore.upsert` takes the shape from the plan and keeps state,
branch and pull request, and demotes a unit of the change that the plan no longer contains to `unplanned`. Started units are never
touched: their groups reach the planner marked `(built by <unit>)`. `cmd_replan` prints the number of calls, then the differences
after the fact. `abk tags` validates the headings of one change or all of them and writes nothing. `abk config --migrate` already
shows the pattern for a command that edits a human-authored file: it edits the text, verifies the result parses, and refuses when it
cannot.

The sizing change (per-tier ceilings) puts a digest of the ceilings and the `review:` section into the plan record, so a plan made
under different ones can be recognised.

## Decisions

- **Stale is a property of the plan record, not of the tasks hash.** The plan record keeps the `tasks.md` digest it has now and a
  second field, the digest of the policy it was planned under. A plan is stale when that second field is missing or differs from the
  current one. The two must stay separate: if the policy went into the tasks digest, the tick's own rule (plan when the digest moves)
  would replan every open change at once, unattended, which is the cost this change exists to ration. A tick therefore reports a
  stale plan and never plans one; `has_work` does not count it, so a stale plan does not keep ticks busy.
- **The report needs no model call because it counts what is stored.** It cannot know what the new units would be without asking the
  planner, so it says what it can: per active change the plan state (`current`, `stale: <why>`, or one of the states `abk replan`
  already lists), the units that have started (the states `cli/pipeline.py` treats as started) against those that have not, the
  groups they carry, and whether a replan would call the planner (one call, or none when every group is taken). The total is the
  sum.
- **The preview is the real planning run against copies.** `--dry-run` runs the same planning code against copies of the unit store
  and the plan records in a temporary directory, so what it prints is what a replan would have stored, and nothing it opens for
  writing is a stored file. The code that asks for and checks a plan is separated from the code that stores it, so one planner call
  serves both a preview and, when it is allowed, the application: a replan never calls the planner twice for a change. The preview
  uses the same printing as the replan's differences, with the review tier, the estimate against the tier's ceiling, and the joins
  added.
- **Started work is the existing rule.** `upsert` keeps a started unit as it is, the planner is told its groups are built, and the
  preview prints each as `kept: <unit>, <state>`. There is no new mechanism; the change gives it a report and a test over a
  partly started change with a different ceiling.
- **A refused plan changes nothing but the record of the attempt.** The stored units stay as they are. The plan record keeps the
  policy digest of the plan that stands, so the change still reads as stale, and notes the reason and the attempt, so the tick's
  ordinary retry limit (`max_plan_attempts`) applies and a refusal is never retried without end. The replan prints the reason, the
  refused unit ids and that the old plan stands.
- **Drops need a person.** A unit of the change that the new plan omits would become `unplanned`; a replan lists each (its id, state
  and groups) and applies nothing for that change unless `--accept-unplanned` is given. The same list is part of the preview. A
  change with no drops needs no flag. This turns what the replan prints after the fact today into what it prints first.
- **Order and quantity.** `--stale` selects every change whose plan is stale and not waiting or given up; `--limit N` keeps the first
  N of the selection in order of the change's most urgent group priority (the `Priority:` lines), then by name. A change that is
  waiting for an outage (its next try ahead) or given up on the same text is skipped and listed, and `--failed` remains the way to
  select those. The first change to meet an outage stops the run and says the rest were not tried, since they would meet the same
  one; a wait uses no attempt, as for any plan.
- **`abk tags --fix` is a text edit.** For each open change it finds the lines the heading parser reads as task-group headings, and
  replaces only the test-kind tag in them (`[unit-test]` with `[unit-test]`, `[e2e-test]` with `[e2e-test]`), leaving every other byte
  alone, line endings included. It then parses the new text and compares it with the old parse: the same groups in the same order
  with the same repo, flags, title and tasks, and the kind equal to the old one under the compatibility mapping. Anything else, a
  change with other tag errors, a file that cannot be read or written, or a result that does not parse the same, is refused with the
  reason and nothing is written for that change. The write is atomic. The planning repo is tracked by git, so there is no backup
  file; `git diff` is the record. `--dry-run` prints what would change. A change already in the new spelling is reported unchanged.
  Only headings are touched: prose that mentions `unit-test` is not.
- **A tag rewrite is not an edit of the specification.** The tasks digest ignores the spelling of the test-kind tag, and a record
  made from the old spelling still counts as current, so rewriting tags does not make a plan stale or have the tick replan it.
- **Nothing in the pipeline writes `tasks.md`.** The command lives in the CLI for a person; a test runs a tick, a replan and a
  planning pass over old tags and checks the file is the same bytes after.
- **No acceptance group.** Every behaviour is a command's output or a file edit over a temporary planning repo, which the existing
  replan driver in `tests/cli/replan_driver.py` already exercises through `main()` with a stand-in planner.

## Risks

- **The cost of the planner calls.** A migration of every open change is one call each; `--stale --limit N` and the report keep it
  to what a person chose, and a refusal uses an attempt, not a loop.
- **A plan the planner refuses.** The old plan stands, the reason is printed, and the person can edit `tasks.md` or try again; a
  change that keeps refusing gives up at `max_plan_attempts` and is then selected only by `--failed`.
- **The preview and the application disagree.** They are the same code on the same planner reply; the application writes what the
  preview showed, and a test compares the two over the same fixture.
- **A started unit whose groups the new plan would split.** It is never reshaped, so the unstarted remainder of the change is sized
  around it; a test covers a change with one merged unit and two unstarted ones.
- **Depends on the sizing change** keeping the policy digest apart from the tasks digest. If it folds both into one hash, the
  tick's own planning rule replans every open change, and this change's staleness rule has to change with it.
