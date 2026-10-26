# Proposal

## Why

Finding that a unit needs a prerequisite only after it has run is ordinary. A unit fails for a cause
outside its own work (a tier 2 test broken by an earlier change), a change is written to fix that,
and a `Needs: <change> group N merged` line is added to the failed group so the unit waits for it.

Today that line does nothing for the unit it was written for. `link_needs` records the dependency
and the merge gate on the unit whatever its state, but only a `planned` unit is held by it. `abk
requeue` of a `failed` or `held` unit with a saved thread resumes it straight to `running`, past the
gate, so it reruns and fails on the same cause. A running unit gets the edge too, and a new
same-repo dependency can send it back as `UPSTREAM_WENT_BACK` or `BASE_CHANGED` without anything
saying a gate was added. Nothing logs the gate landing on a started unit and no spec says what
should happen.

## What Changes

- **A gate holds a started unit.** A `failed` or `held` unit whose gate is unmet is not resumed by
  `abk requeue`: it goes to `planned` with the cause `gated`, keeping its thread, branch and
  feedback, and the command says what it waits on. When the gate clears the pass resumes it at its
  recorded node, as the requeue would have.
- **A unit that is running is not disturbed.** The gate is recorded and logged; the step in
  progress finishes. A unit later sent back for rework waits at readmission like the above.
- **A merge gate never changes a base.** Adding a `merged` need to a unit that does not stack on the
  dependency changes neither its base nor its upstream state.
- **It is visible:** the first tick that applies a `Needs:` line to a started unit logs it, and
  status and the graph show the unit waiting on the prerequisite.
- **Stated, not left implicit:** editing only a `Needs:` line does not re-plan the change.

## Impact

- agent-build-kit: `link_needs`, the requeue command, the readmission rule, `waiting_on`/`base_of`
  for a merge-gated dependency, the cause set (`gated`), status and the graph page.
