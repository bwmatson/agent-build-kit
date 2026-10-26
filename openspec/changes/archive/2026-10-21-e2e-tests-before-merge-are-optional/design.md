# Design

## Context

A unit of the e2e-test kind runs `Node.E2E` (formerly `E2E`) after review approves and before the push, under the host's e2e lock,
and runs it again when `verify_base` moved the branch onto a new base (`state.moved`). A scheduled whole-suite unit
(`state.scheduled`) reaches the same node and is itself the run. A failure becomes feedback for the build agent or, on a moved base,
a rebase. The pull request body shows the run's results for such a unit and, for a unit-test unit, says no e2e run was required.
After every unit of a change has merged, `verify_change` deploys what the pull requests touched and runs the live tests of the
changed paths with the consumer's credentials, and archive waits for it. The settings for the node are `global_limits.e2e_*` with
per-repo overrides under `tests`, resolved by `e2e_unit_scope(repo, limits)`.

## Decisions

- **The setting follows the existing pattern.** `e2e_before_merge` is a `StrEnum` of `required` and `deferred`, a field of the
  global limits with default `required`, and a field of a repo's `tests` block where unset means follow the global one. A resolver
  `e2e_before_merge(repo, limits)` returns the value in effect, the same shape as `e2e_unit_scope(repo, limits)`. An unknown value is
  refused when the file loads, naming the key, and `abk config` prints the value in effect for each repo.
- **Deferral is a routing decision.** The graph's routing after review, after prepare for an already approved head, and after the
  unit-test node on a moved base each choose between the e2e node and the next step. With `deferred` and a unit that is not a
  scheduled run, they choose the next step. The e2e node itself stays unchanged, so the lock, the failure feedback and the results
  need no new paths. A scheduled run ignores the setting, since it is the suite.
- **Deferral is recorded, not inferred.** The unit gets a stored e2e state, a `StrEnum` of `passed`, `deferred`, `failed` and
  `not-required`. The e2e node records `passed` or `failed`; the routing records `deferred`; a unit-test unit records
  `not-required` when it reaches review. A pushed rework resets the state, so the value always belongs to the head that was pushed.
  A unit stored before this change has no state: the verdict reads it as it reads any missing gate result, which is `full` for an
  e2e-test unit and no floor for a unit-test unit, so nothing becomes more permissive.
- **The pull request says so.** For a deferred unit the verification section reads "e2e-test deferred to verify" and says the live
  tests run after the merge, against the deployed change, and that a failure there is found after the merge. It is a fixed section as
  the other verification text is, so a long description cannot push it out. A unit that passed its e2e keeps today's section.
- **`verify` runs what it runs.** It selects the live tests of the paths the change's pull requests touched, for the deployed
  change, once all its units have merged. It is not changed to run more. Two consequences are accepted and written down: a unit that
  would have run the whole marker (`e2e_unit_scope: full`) has deferred a run that `verify` does not repeat in full, and a failure
  in `verify` says which change failed and not which unit. So that a person can tell, a failed verification's detail names the
  units of the change that deferred their e2e.
- **The verdict reads four states and `allow_deferred_e2e`.** The verdict's e2e input becomes the state above. `failed` is a `full`
  floor as before. `deferred` is a `light` floor in the evidence tier, so a unit that deferred cannot reach `auto`, unless
  `review.auto_land.allow_deferred_e2e` is true, when `deferred` adds no floor. `passed` and `not-required` add none. The key is a
  boolean, default false, in the `auto_land` block and in no other place, and only a person writes it. A floor only raises, so a unit
  that is also on a protected path stays `full`.
- **Documentation.** `docs/configuration.md` gets the setting and its trade, the `abk-config` skill a line, `abk init`'s template a
  commented line, `docs/architecture.md` the node's routing, and `docs/unit-graph.md` the edge that skips the node.

## Risks

- **Problems found later.** That is the setting's cost and it is named in the documentation and the pull request. The default keeps
  today's order.
- **`verify` covers less than the unit would have.** The selection is by the paths the change touched. The deferred-unit note in a
  failure points at the gap; widening `verify` is a separate decision.
- **A deferred unit stacked under others.** Its children build on a branch whose e2e has not run; the same is true of any unit whose
  parent is still in review, and the stack rules are unchanged.
- **The verdict's input changes under the sizing and auto-land work.** The four-state input is defined here, and the verdict's tests
  are extended in place so a later change reads the same enum.
