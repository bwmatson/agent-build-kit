# Tasks

Acceptance: none — scheduling behaviour on the unit store and the requeue command; tier-1 tests over
a unit store and a fake graph engine prove it.

## 1. [agent-build-kit] [tier1] A Needs line added later gates a started unit

Done when a failed or held unit whose gate is unmet waits instead of running, resumes in its
requeued mode once the gate clears, and a running unit is told but not disturbed.

- [x] 1.1 Test: `abk requeue` of a failed unit with a saved thread and an unmet `merged` need leaves
      it `planned` with the cause `gated`, delivers no event, keeps thread, branch and feedback, and
      prints the group it waits for; the same for a held unit.
- [x] 1.2 Test: once the dependency is merged the pass resumes that unit at its recorded node in the
      mode it was requeued with (default, `--rework`, `--restart`), and a requeue with the gate
      already clear resumes at once as before.
- [x] 1.3 Test: adding a `merged` need to a running unit changes neither its state nor its base,
      does not send it back as an upstream change, and logs the wait once across repeated ticks.
- [x] 1.4 Test: an in-review unit sent back for rework while its gate is unmet is `planned` with the
      cause `gated`, and starts when the gate clears.
- [x] 1.5 Test: a change whose only edit is a `Needs:` line is not planned again and `link_needs`
      applies the gate on the next tick; `abk status` lists the unit as waiting on the group.
- [x] 1.6 Add the `gated` cause, check the gate in the requeue command and the readmission rule with
      the scheduler's own `waiting_on`, keep merge-gated edges out of `base_of` and
      `upstream_incomplete`, and log the first application of a gate to a started unit.
- [x] 1.7 Show a gated unit in status and on the graph page, update `docs/cli.md`,
      `docs/unit-graph.md` and the pipeline skill, and add a changelog entry.
