## Context

Code at agent-build-kit `origin/main` (c6d2aedd):

- **Old route** (setting off, one pair for the unit): `implement` (`graph/nodes.py:1424-1475`) returns `produced_nothing: r.branch_commits(tree, ref) == 0`
  (`1473`). `after_implement` (`2634-2639`): a stop, else `tests` while `more_groups`, else `unit_test` if `produced_nothing`, else `checks`. The step is
  gated between steps for a unit that produced nothing (`_step`, `527`). `unit_test` (`1939-1990`) runs the whole repo's tests when `produced_nothing`
  (`whole_repo`, `1958`); a failure saves feedback and stops the unit (`1980-1984`). `after_unit_test` (`2664-2670`) sends `produced_nothing` to
  `satisfied`, which sets `SATISFIED`, clears feedback and predecessor notes, releases dependents, closes a stale PR and marks the tasks done (`2096-2130`).
- **Stubbed route**: `tests` -> `stub_checks` (commits `test:` on a pass) -> `implement` (commits `feat:`), then `unpaired` (`1409-1418`) runs
  `group_progress` (`commit_order.py:155-168`) over `branch_subjects`; a group count short of `state.group` stops the unit (`1457-1459`), before
  `produced_nothing` is computed and before `group`/`more_groups` advance (`1463-1475`).
- **`GroupStep`** (`pipeline/stack_runner.py:228-236`) carries `test_only` (already on main). `group_progress` does not yet read it; the sibling change
  extends it.
- **Zero-commit tests agent**: see the proposal; `tests` and `stub_checks` complete cleanly and commit nothing (`wiring.py:859-861` returns None for an
  empty stage). The tree is whatever the agent left: if it left uncommitted stubs or tests, `stub_checks` commits them and the branch is not zero-commit,
  so the rule does not apply.

## Decisions

- **The rule is the old build's own: `branch_commits(tree, ref) == 0`.** "Nothing of its own on the branch" is exactly what `produced_nothing` already
  means, what `satisfied` is judged on ("Judged on the branch and the checks, never on a step's report of itself", `satisfied` docstring) and what a
  resumed unit asks (`branch_commits` docstring). Reusing it makes the stubbed and old builds reach the same state for the same branch, with no new
  predicate. Rejected: "the agent said it built nothing" (a step's report of itself); "the group's pair is absent from the base" (needs a content
  check the pipeline does not have); "skip the count whenever `test_only`" (does not cover groups 3-4 of a unit whose work was built elsewhere).
- **Compute the count once, before the stop.** `implement` reads `branch_commits` right after the agent and commit steps, uses it for the stop test
  (`zero -> no stop`) and returns it as `produced_nothing`, so the stop and the routing read one number. The existing comment "counted on the branch, not
  taken from the commit step" still holds.
- **Skipped after every group, not only the last.** A zero-commit group that is not the last cannot know whether a later group will commit. Skipping
  the stop at an early group is safe because the count after the last group still runs whenever the branch has a commit: the group_progress walk would
  see the later group's subjects as out of position and stop the unit. The cost is that a mixed unit (not in this change) spends its later groups'
  agent calls before it stops. Stopping early on a zero-commit group instead would keep failing the unit of `reviewers-are-told-where-to-look/4`'s kind
  when its earlier groups were built elsewhere too.
- **The pair message names the first group without a pair.** `unpaired` returns the group `group_progress(...).done` points at when it is below the
  group just built, else the group just built. Where the count stopped a unit before, the two are the same group, so existing messages do not change.
- **Route unchanged.** With `produced_nothing` true and no more groups `after_implement` already goes to `unit_test`; with more groups it goes to
  `tests` and the flag is recomputed after each group, so only the last group's value routes. `unit_test` and `satisfied` are the existing nodes:
  no new state, no new edge in `docs/unit-graph.md` (the `implement -> unit-test` edge, "nothing new", already exists and is now reachable from the stubbed
  build, as its label says).
- **Resume.** A zero-commit unit has `existing == 0`, so `resumed` returns `{}` and `after_prepare` picks `tests`: a requeued unit that was stopped
  with the pair message is rebuilt from its first group, passes through the same steps and ends `satisfied`. A unit killed after its agents ran and before
  `satisfied` repeats them; it is the same cost as the old build's `tests` when nothing is on the branch. A `satisfied` unit is not resumed.
- **Test-only interaction** (sibling `a-test-only-group-commits-no-pair`): its stub-check step makes the lone `test:` commit, advances `group` and
  `more_groups`, and counts the satisfied groups after the last group (tasks 4.3, 4.6 there). The rule here is on that count too: when the branch has no
  commit of its own the count is skipped and `produced_nothing` is set from the same `branch_commits`. A unit of only test-only groups whose tests
  agent wrote nothing therefore ends `satisfied`; a test-only group that did commit has a commit of its own, so the count runs and is full. This change
  adds the rule where the code is today (`implement`) and states it for the sibling's code; the first to land carries the second's task as a test.
- **Setting off is untouched**: `unpaired` is reached only when `group_step(state)` is not None, i.e. in a stubbed build (`group_steps` is empty
  otherwise, `1393`); the change is inside that branch.

## Risks

- **A stubbed unit that really failed to build ends `satisfied`.** The same risk the old build takes; `unit_test` over the whole repo must pass first,
  and a tests agent that wrote nothing for a group whose work is absent leaves the unit-test (or the e2e/verify steps) the check. The unit's
  tasks are marked done only after that pass.
- **A mixed unit now stops later.** Stated under "Not in this change"; the message names the right group.
