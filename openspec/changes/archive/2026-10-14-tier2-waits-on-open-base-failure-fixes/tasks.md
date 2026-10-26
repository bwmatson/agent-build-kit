# Tasks

Acceptance: none — the gate, the exemptions, the park and the resume are decided by a record file, a fake runner and the fake graph the tier 2 node tests use; the first real second unit to reach tier 2 while a fix is open is the live confirmation.

Priority: 1

## 1. [agent-build-kit] [tier1] A unit about to run a full tier 2 run waits on the open fix change of a base failure

Needs: tier2-runs-on-a-schedule group 1 — the gate reads the run's scope from the scope function and the `tier2_unit_scope` setting (per repo, with a `limits` default) that group adds

Done when a unit that reaches a full-scope tier 2 step while a recorded base failure's fix change is open in its repo is parked gated on it before any lock or test, the fix's own units, units already waiting on it and units of other repos run, only base-failure records hold a unit, an own-scope run and a unit with no tier 2 test of its own are never held, and the status counts the waiting units.

- [x] 1.1 Test: `tests/graph/test_tier2_gate_waits_on_open_fix.py` drives the node with a record of a base failure whose fix change is open and a fake runner, and asserts a second unit of the repo gains a `Needs:` line on each of its groups, is parked planned and gated with a resume requeue, `run_tier2` is never called, the stack lock is never taken and no change is written.
- [x] 1.2 Test: the same file asserts a unit that has not reached tier 2 when the record is written has no line until it arrives, that nothing scans other units when a record is appended, and that a unit run again after a restack is held the same way.
- [x] 1.3 Test: the same file asserts the parked unit holds no place and is listed as waiting on the fix change, and that with the fix change's unit in review, or merged, `release_gated` resumes it and the node runs tier 2 and does not park it again because its `Needs:` line is there.
- [x] 1.4 Test: the same file asserts a unit of the fix change itself, a unit with a `Needs:` line on it and a unit of another repo run tier 2 with no new line, a unit of fix A is held by open fix B and gains a line on B only, and a record whose fix change is archived holds nobody.
- [x] 1.5 Test: `tests/pipeline/test_tier2_gate_records.py` asserts a unit's own failure, a flake and a run that failed on an environment outage write no record and hold no unit, that `limits.tier2_base_runs: 0` leaves the record empty so no unit is held, and that a run in flight when a record is written is classified and judged as before.
- [x] 1.6 Test: the same file asserts a fix change whose units were closed keeps the unit waiting with the existing listing, and that the gate adds no release, no command and no line of its own for it.
- [x] 1.7 Test: `tests/graph/test_tier2_gate_scope.py` drives the node with a record of a base failure whose fix change is open and asserts that under `own` a unit that added a tier 2 test runs its own tests with no `Needs:` line, no park and no record read, that a unit with no tier 2 test of its own is not held and takes no lock, that under `full`, with a dev stack script, and with a profile that cannot select tests the unit is held as before, and that the gate asks the scope function and reads no setting itself.
- [x] 1.8 Test: `tests/cli/test_status_preexisting_waiting.py` asserts a `pre-existing:` line ends with `3 units waiting` for three waiting units, ends with `1 unit waiting` for one, and is unchanged for none.
- [x] 1.9 Add the function in `pipeline/untouched_failures.py` that returns the open fix changes holding a unit (record entry, open change, repo of the recording unit, not its own change, no `Needs:` on it), a runner callable beside `build_on_preexisting` that calls `wait_on_preexisting(..., wait=True)` for each, the check at the start of the `tier2` node before `run_tier2`, made only when the scope function of `tier2-runs-on-a-schedule` says the run is full, that returns `park_for_fix`, and the count on each status line. Confirm the places design.md marks UNVERIFIED and correct the design where the code says otherwise.
- [x] 1.10 Document the gate in `docs/architecture.md` and the pipeline skill, state in `docs/architecture.md` that a same-repo fix releases the unit once it is in review, and add a changelog entry.
