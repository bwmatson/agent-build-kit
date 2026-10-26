# Design

## What was checked, and where

Amended before any code (the change is unplanned): its priority is 1, and its gate holds only full-scope runs. Everything below was read against
`origin/main` and still holds; the scope function it now asks is read against the design of `tier2-runs-on-a-schedule`.

Read-only against agent-build-kit `main`:

- `graph/nodes.py` `tier2` (about 1685): `ok, snapshot = r.run_tier2(cwd=..., base=base)` is the first thing it does after saying `tier 2`;
  `wait_for_preexisting` (about 1723) records each pre-existing failure and, when nothing else failed, calls `park_for_fix`; `park_for_fix`
  (about 1315) is `hold(PLANNED, note, note, cause=Cause.GATED)` then `set_gated_requeue(unit.id, RequeueReason.RESUME)`.
- `pipeline/wiring.py` `Tier2Session.run` (about 1934): the stack lock is taken inside it by `_locked()` (`stack_lock`), after the dev-stack
  branch and before any command runs. A check placed in the node before `run_tier2` is therefore before the lock, before the dev-stack
  run and before any test. `build_on_preexisting` (about 1123) builds a `PreExisting` entry and calls `wait_on_preexisting`.
- `pipeline/untouched_failures.py`: `wait_on_preexisting(inst, entry, unit, *, wait, say)` calls `ensure_fix` (takes `preexisting.lock`,
  reports `exists:` or `would write:`) and, when the fix is not the unit's own change and `wait` holds, `add_needs_to_unit`, which gives each
  group of each member a `Needs: <fix> group 1 — failing test <test> on the base` line (`pipeline/flakes.py` `add_needs`, which does nothing when
  a line on that change is already there). `preexisting_record(inst)` is `<state_dir>/preexisting-failures.jsonl`; an entry has `test`, `unit`,
  `change` (empty for the fix change's own unit), and `counts()` gives each test once with its latest non-empty `change`.
- `pipeline/failure_record.py`: an entry names its unit, not its repo; the repo is the stored unit's `repo`.
- `pipeline/flakes.py` `open_fix_change`: a fix change is open while its directory is under the changes directory and not archived.
- `pipeline/units.py` `waiting_on`: a same-repo parent is waited for until it is in review or merged (`REVIEWED`); a closed one is not
  in `REVIEWED` and so keeps the dependent waiting. `release_gated` (`cli/pipeline.py` about 1519) resumes a planned, `gated` unit with a stored
  requeue once `waiting_on` is empty.
- `config.py` `tier2_base_runs` is `0` or `1`; at `0` `Tier2Session._judge` returns before classifying, so nothing is recorded.
- `cli/pipeline.py` status (about 520) prints `pre-existing: <test> — failed on the base N times, fix <change>`.

## The gate

The gate applies only to a run that executes the whole marker. An own-scope run executes only tests the unit added or changed, so it cannot meet a
test that fails on the base without the unit's having touched it (a failure in a changed file is the unit's own by classification), and an open fix
elsewhere need not hold it; a unit that runs no tier 2 test takes no lock and runs nothing to hold. The `tier2` node asks the scope function
`tier2-runs-on-a-schedule` group 1 adds, the one `Tier2Session.run` uses, before the gate: `full` (by the repo's `tier2_unit_scope` in effect, by the dev stack script,
by a profile that cannot select tests, by an unreadable list of the unit's tests, and, by the rule group 2 of that change adds to the same function, a scheduled unit) is gated; `own` is not, with tests or
without. The setting is read by its documented name, `tier2_unit_scope` (the repo's `tests` value over the `limits` default), through that function and nowhere else. That is why this change
needs group 1 of that change (a `Needs:` line without `merged`, so the unit starts on its branch): the gate cannot be written before the function
exists.

In `tier2`, before `r.run_tier2`, and only for a full-scope run, a runner callable (`on_tier2_gate`, built beside `build_on_preexisting`) asks `untouched_failures` for the
open fix changes that hold this unit, and for each calls `wait_on_preexisting(..., wait=True)` with the recorded entry. If any returned a
change, the node returns `park_for_fix(note)` and `run_tier2` is never called, so the stack lock is not taken and the dev-stack script is not
started. Otherwise it goes on to `run_tier2` unchanged.

A fix change holds a unit when all of these are true (the third is asked first, before any record is read):

1. **A record names it.** The latest recorded entry of some test has a non-empty `change`, and that change is open (`open_fix_change`'s notion:
   a directory in the changes directory, not archived). A merged and archived fix holds nobody, and a test that failed again is held by its
   successor, which `counts()` and the ensure step already name.
2. **Same repo.** The repo of the unit named by the record's entry is the repo of this unit. The record has no repo of its own and gets none:
   the stored unit has one.
3. **Full scope.** The run the unit is about to make is a full-scope run (above). An own-scope run is never held.
4. **Not exempt.** This unit's change is not that fix change, and no group of any member of this unit already carries a `Needs:` line on it.
   The second exemption is also what lets a unit that is released and restacked onto the fix's branch run tier 2: it waits on the fix, so it is
   exempt, and it is not parked a second time.

The exemption is per fix: a unit of fix A, which has no `Needs:` on fix B, is held by open fix B, as any unit is.

The call writes nothing: only open fix changes are passed to it, and `ensure_fix` for an open change reports `exists:` and returns. Its
`Needs:` reason text is the one the park already writes.

## Editing a unit that is running

At the `tier2` node the unit is the running unit, and `wait_for_preexisting` already does the same thing for the unit that met the failure:
`add_needs_to_unit` edits that unit's own group text from inside its own node, and the node parks the unit itself. This is not an edit made
under another run, and the standing rule that a `Needs:` line added to a running unit does not interrupt it
(`needs-start-on-the-parents-branch`) is untouched: here the unit stops itself, at a point where it holds nothing. The gate relies on that and
adds no editing rule.

## What the wait does

The unit is `planned`, cause `gated`, with a stored requeue `resume`, exactly as for the failure's own unit and for a flaky test. It frees its
place and shows as waiting through the existing rules (`failed-units-waiting-on-a-prerequisite-free-their-slot` covers a unit that is
failed; a planned unit that waits is already blocked and not counted). `release_gated` resumes it once `waiting_on` is empty. For a same-repo
fix that is when the fix's unit is in review, not only when it has merged: the unit is restacked onto the fix's branch, so its tier 2 run
includes the fix. This differs from the wording of the earlier change, "when it merges", which is what a cross-repo fix would do; this change
states the actual rule and relies on it. The resumed thread lands on the `tier2` node again, where the gate finds the `Needs:` line and
lets it through.

## Other rules

- **Other units.** No step scans units when a record is written. A planned unit that has not reached tier 2 meets the gate on arrival. A
  unit in `in_review` that is sent back for rework and comes to tier 2 again meets it then.
- **A run in flight** is past the gate; it finishes, is classified and, if its failures are pre-existing, goes through the existing path.
- **Outages.** The gate reads only the record. An environment outage is kept out of the record by the classification and by the outage rules
  before it; the gate adds no path from an outage to a `Needs:` line.
- **An abandoned fix.** A fix change whose units were closed stays open in the changes directory, so units still wait on it, and a unit that
  waits on a closed prerequisite is treated as any such unit is: a planned one stays blocked and listed, a failed one gets the line
  `wait ended: <prerequisite> closed, requeue to retry` of `a-failed-unit-resumes-when-its-wait-ends`. A person clears it the existing way
  (archiving or removing the change, or `abk requeue`). Nothing is added.
- **`tier2_base_runs: 0`.** No base run, no record, no gate. No setting is added.
- **Status.** Each `pre-existing:` line appends `, N unit(s) waiting` when `N` is above zero: the units, other than the fix change's own, whose
  `waiting_on` names a unit of that fix change. The wait itself appears in the existing blocked listing and on the graph.

## UNVERIFIED

- Whether `waiting_on` of a unit parked at the gate names the fix change's unit when the fix change's groups are not yet in the unit store
  (a fix written this tick, before the next plan). The builder confirms the units exist by then or the gate reads the change's groups the way
  `add_needs` resolves them, and corrects this document.
- Whether a unit in `in_review` that is sent back for rework can be parked at `tier2` without disturbing its pull request. The node holds as it
  already does for the unit that met a failure; the builder confirms and corrects.
