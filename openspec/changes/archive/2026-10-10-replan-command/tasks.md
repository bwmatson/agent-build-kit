# Tasks

Acceptance: none — the planner is faked at its boundary as in the existing planning tests; a real call is the same code a tick uses.

Priority: 1

## 1. [agent-build-kit] [tier1] Plan named changes again on demand

Done when `abk replan` plans the changes it is given or selects, leaves started work alone, prints what changed, and a tick behaves as before.

- [x] 1.1 Test: names, a unit id mapped to its change, `--all` and `--failed` select the right changes; no selector lists each change with its
      plan state and plans nothing; an unknown name, a change with tag errors and a change without `tasks.md` are refused with their
      message; the exit status is 0, 1 or 2 as described.
- [x] 1.2 Test: a named change is planned although its hash is recorded, and its record is written with the new hash, no attempts and `ok`;
      a change that gave up is planned by `--failed` and its attempts start over; `--forget` clears records and makes no planner call; a tick still
      skips a change whose hash matches.
- [x] 1.3 Test: a running, in-review, failed, held, merged and satisfied unit keep state, branch, pull request and history; a planned unit takes
      the new shape; an unstarted unit the plan drops becomes `unplanned`; a dropped join is reported.
- [x] 1.4 Test: a stale dependency is removed by a replan and a dependency a `Needs:` line asks for is kept; the output lists the differences and
      the started units left alone, and nothing for an unchanged unit.
- [x] 1.5 Test: the recorded plans are written atomically under a lock and two writers do not lose an update.
- [x] 1.6 Give `plan_all` a selection of changes and a forced mode with a result for each change, add the command and its parser beside
      `requeue`, lock and atomically write the recorded plans, and name `abk replan` in the give-up and failing-plan messages.
- [x] 1.7 Document the command in `docs/cli.md`, when to use it in the pipeline skill (a stale dependency, a change that gave up, neighbours that
      changed) and the planning paragraph of `docs/architecture.md`, and add a changelog entry.
