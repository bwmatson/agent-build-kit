## Why

With `builders.per_group_commits` on, a build counts the `test:`/`feat:` pairs on the branch after each group (`unpaired`,
`src/agent_build_kit/graph/nodes.py:1409-1418`, called from `implement` at `1457-1459`). With it off, `implement` ends by setting
`produced_nothing = r.branch_commits(tree, ref) == 0` (`1473`), `after_implement` sends a unit with no more groups and `produced_nothing` to
`unit_test` (`2634-2639`), `after_unit_test` sends `produced_nothing` to `satisfied` (`2664-2670`), and `satisfied` (`2096-2130`) sets the unit state
`SATISFIED` with the note "nothing to add and unit-test passes — satisfied" and closes any pull request. In the stubbed build the pair count returns
`stop(...)` at `1457-1459`, before `1473`, so a unit whose work is already on its base can never reach that route.

On 2026-10-21 unit `reviewers-are-told-where-to-look/4` stopped there: group 4's work had been built by group 3's unit and was on the base. The
agent made no commit (its words: new copies of passing tests would break the rule that a new test must fail first). The same unit in the old build
ends `satisfied`. The two flows must reach the same state for the same branch.

What the `tests` and `stub_checks` nodes do when the tests agent commits nothing was read in code, and confirms the log (both passed cleanly):

- `tests` (`nodes.py:1302-1331`) calls the agent and, in a stubbed build, returns `stub_loop: True` with no commit (`1328-1329`).
- `stub_checks` (`1333-1352`) runs lint, format and types over the tree (`run_stub_checks`); on a clean tree they pass, and `r.commit` (the
  `commit` closure in `pipeline/wiring.py:833-880`) finds nothing staged (`git diff --cached --quiet`, "Nothing staged: an empty commit would be a
  lie") and makes no commit. It returns `stub_loop: False`, so `after_stub_checks` (`2626-2627`) goes to `implement`.
- `implement` calls the implementation agent (it too commits nothing), then reaches the pair count with an unchanged branch: `group_progress`
  (`pipeline/commit_order.py:155-168`) finds no `test:` subject, `done = 0`, and `unpaired` returns "group N (title)".

A resumed run of a zero-commit unit: `resumed` (`nodes.py:1082-1099`) returns `{}` when `existing` is 0, `after_prepare` (`2614-2615`) sends a unit
with `base_commits == 0` to `tests`, so the unit is rebuilt from the first group; it reaches the same point and, with this change, the same end.

This was found by the soak of `builders.per_group_commits`. It does not count against the soak's criterion of "no push-gate refusals" (the design of
`tests-are-stubbed-checked-and-committed-per-group`): the unit was stopped by its own pair-count check in `implement`, not refused by the push gate.

## What Changes

- **In a stubbed build, `implement` decides "nothing of its own" first.** After the agent step and the commit step it counts
  `branch_commits(tree, ref)`. When it is 0 the pair-count stop is skipped, and `produced_nothing` is set from the same count as today, so the
  existing routing takes the unit to `unit_test` after the last group and to `satisfied` on a pass.
- **A unit with some commits of its own is judged as now.** A stubbed branch with at least one commit and a missing pair still stops with
  "the branch holds no tests and implementation pair for group N (title)". The message now names the first group the branch has no pair for, which is
  the group just built in every case that stopped before (a pair count is checked after each group), and is the right group once a zero-commit group
  has been passed over.
- **The route is the existing one.** No new state, no new node, no new edge: `implement` -> `unit_test` (`produced_nothing`) -> `satisfied`. This
  moves the old build's process earlier in the stubbed flow. Nothing is committed. A failing `unit_test` takes the existing failure route
  (`stop("unit-test failed")`, feedback saved with source `unit-test`).
- **Test-only groups (sibling `a-test-only-group-commits-no-pair`).** Its group commits one `test:` and no `feat:` and skips `implement`; its
  stub-check step advances the group the way `implement` does and counts the pairs after the last group. That advance sets `produced_nothing` from
  the same branch count and skips the count the same way, so a unit of only test-only groups with no commit also ends `satisfied`; a test-only group
  with its `test:` commit has a commit of its own and is not affected. Whichever change lands first, the other follows the rule in the spec.
- **Docs and changelog.** `docs/architecture.md` and `docs/unit-graph.md` (the `implement` row and the `implement` edges) say so; one changelog bullet.

## Impact

Units whose groups were all built elsewhere end `satisfied` in the stubbed build as in the old one, with no push and no pull request opened (a pull
request already open is closed by `satisfied`). Nothing changes with the setting off: `produced_nothing`, the routing and `satisfied` are the
existing code, and no task here touches the old route. Both flows stay: the person decided to keep them side by side.

## Not in this change

- **A mixed unit** (an earlier group already built on the base, a later one needing work). Today it stops with the pair message: the branch holds
  only the later group's pair, `group_progress` walks the titles from the first group, finds `done = 0` and `unpaired` reports a missing pair. After
  this change it still stops with the pair message, but one group later: the earlier group's zero-commit `implement` is passed over (it cannot know a
  later group will commit) and the stop comes after the last group, naming the first group with no pair. It spends the later groups' agent calls first.
  A real fix needs the build to match groups to commits other than by position, and is a separate change.
- **Skipping the agent calls of an already-built group.** In the stubbed build the tests agent and the implementation agent are still called and
  commit nothing, as in the log of `reviewers-are-told-where-to-look/4`; the unit only ends `satisfied` instead of failing.
- **Removing the old route** or either flow. Neither is touched.
- **The pair rule for a branch with commits**, the push gate, `satisfied`, `unit_test` and the setting's name or default.
