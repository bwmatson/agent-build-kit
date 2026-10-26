## Why

Code at agent-build-kit `origin/main` (e9a94029); every line number below is against it.

With `builders.per_group_commits` on, a group's tests step writes the tests and stubs and `stub_checks` (`src/agent_build_kit/graph/nodes.py:1416-1439`) commits
them as `test: <title>` once the static checks pass: `made = r.commit(...)` at `1426`. When the tests agent left nothing to commit, `made` is 0 and no
`test:` commit exists; for a group that is not test-only nothing else happens there (`1429-1430`). The `implement` step (`1615-1665`) then commits the
implementation as `feat: <title>` when the agent changed files (`1651`).

The merged change `a-group-built-by-an-earlier-group-is-recorded` handles the group whose agents leave BOTH steps empty: `record_built` (`1554-1590`) records
an empty marked `test:`/`feat:` pair, but only when the head has not moved (`r.head(tree) != state.head` returns None, `1570-1571`), that is, only when the
implementation step also left nothing. It does nothing when the tests step committed nothing and the implementation step changed files, because `made` is then
non-zero (`1562`). No pair is recorded, and `settle_group` (`1592-1608`) asks `unpaired` (`1502-1512`), which reads `branch_progress` (`1514-1523`) ->
`group_progress` (`src/agent_build_kit/pipeline/commit_order.py:162-181`). That walk takes, for each group, a `test:` subject then a `feat:` subject with the
group's title from the front of the branch; a `feat:` where a `test:` is expected ends the walk (`172-174`) and the unit stops with
`the branch holds no tests and implementation pair for group <n> (<title>)`.

Incident, 2026-10-22: `reviewers-are-told-where-to-look/4` (groups 3 and 4). Group 3's builder wrote the tests group 4 needed, so group 4's tests step found
nothing to commit. An earlier attempt's implementation step for group 4 changed a changelog blank line and a stale assertion and committed `feat: <group 4
title>`: the branch read `test g3, feat g3, feat g4`. On the next attempt the merged change recorded the empty pair, giving
`test g3, feat g3, feat g4, test g4 (empty, marked), feat g4 (empty, marked)`, and the unit stopped with the pair message for group 4. The branch was repaired by
hand. The cause is not that attempt's accident: any group whose tests already exist (so its tests step commits nothing) and whose implementation step makes a
real change ends with a lone `feat:`.

What the rest of the system does with the pieces was read in code (all already merged by the earlier change, and pinned there by tests):

- **`half_recorded`** (`nodes.py:1525-1533`): the group is the next one (`progress.done == state.group`), its `test:` is on the branch (`progress.tests_made`)
  and the tip commit is a marked empty one (`recorded_built`, `commit_order.py:138-144`). `implement` runs its agent in that case even though the head has
  moved since the group began (`1619-1622`), and `record_built` then records only the `feat:` after the whole-repository unit tests pass (`1566-1590`).
- **Resume** (`resumed`, `nodes.py:1141-1154`): a branch whose tip is `test: <title>` of the next group resumes at `implement` (`RESUME_IMPLEMENT`).
- **Commit helper**: `commit_built(message, *, cwd)` (`src/agent_build_kit/pipeline/wiring.py:922-943`, a runner field at `pipeline/stack_runner.py:1563`, beside
  `commit` at `1561`) makes an empty commit with the trailers `Unit:`, `Adopted-From:` (when set) and `Already-built: yes`, one attempt, hooks on, no gate.
- **The push gate and a restack**: an empty commit is `docs` kind to `check_structure`, is not a tests commit to the gate, so is neither lint-checked nor red-run
  (`gate.py`, as the earlier change read it), and `git rebase --onto` keeps a commit that starts empty.

## What Changes

- **A group with no new tests gets an empty, marked `test:` commit.** In a stubbed build, for a group that is not test-only, when `stub_checks` has passed the
  static check and the tests step committed nothing (`made == 0`), the branch already holds at least one commit of its own, `progress.done == state.group`, and
  the branch holds no `feat:` of this group's title where its `test:` should be (a stray), `stub_checks` makes one empty commit with `commit_built`:
  `test: <group title>`, the group's usual body, then one sentence that the group adds no new tests, and the trailers `Unit:` and `Already-built: yes`. It makes no
  model call and runs no tests: the commit claims only "this group adds no new tests".
- **What follows is the existing path.** The implement step runs as today. If the agent changes files, the normal `feat:` commit completes the pair (an empty
  `test:` then a real `feat:`). If it changes nothing, `half_recorded` is true, `record_built` runs the whole-repository unit tests and records only the empty
  `feat:`. Every group ends with the same two-commit shape.
- **A clearer stop for a lone `feat:`.** When `group_progress` finds the `feat:` of the group where its `test:` was expected, the stop names it: `a feat: commit
  for group <n> has no test: commit before it (feat: <title>)`, instead of the generic pair message. A branch with a stray commit from an older attempt is then
  diagnosable at a glance.
- **A second rule: real tests that already pass.** When the group has a real `test:` commit (the tests agent committed tests), the implement step commits
  nothing, and the whole-repository unit tests (`run_unit_test(whole_repo=True)`, which include the new tests) pass, `record_built` records only the empty marked
  `feat:` for the group, with the reason in its body: the tests pass without further implementation because the implementation already exists. When that run
  fails the unit stops as today, so stubs and tests with no implementation still stop. Incident: `a-unit-over-its-tier-is-held-and-split/13` (groups 11, 12, 13),
  stopped 2026-10-22 15:40 with `the branch holds no tests and implementation pair for group 12`: the tests agent wrote real tests for group 12 (real `test:`
  commit `eed46f86`), they were not red because group 11's implementation already covered every behaviour ("The five group 12 tests pass without any source
  change"), the implement agent changed nothing, and `record_built` returned None at `progress.tests_made and not resumed` (`nodes.py:1568-1569`).
- **Unchanged**: a branch with no commit of its own (the zero-commit route to `satisfied`), test-only groups, a group whose tests agent did commit and whose implementation changes something, the build
  with the setting off, the push gate, a restack, the rule that the empty `feat:` needs the whole suite to pass, and that real stubs and tests with no
  implementation still stop the unit (their suite fails).
- **Docs and changelog.** `docs/architecture.md` (the stubbed build paragraph and the push gate paragraph), the `stub_checks` and `implement` rows of
  `docs/unit-graph.md`, and one changelog bullet.

## Impact

A unit whose later group reuses tests an earlier group wrote no longer stops when its implementation step changes something: its commit list shows an empty
`test:` (body: the group adds no new tests) and the real `feat:`. The empty-pair case of the merged change now records its `test:` earlier (at the end of the
tests step, not after the implementation step); when the whole-repository unit tests then fail, the empty `test:` stays on the branch and the unit stops with the
pair message, and a requeue resumes at `implement` (the marked tip), as a kill between the two commits does. The squash merge drops the empty commits. A group with real tests that pass and no implementation change now ends with its real `test:` and an empty `feat:`; the reviewer reads the reason in the commit list.

## Not in this change

- **Repairing a branch that already carries the stray order.** A person fixes it; the repair for a branch such as `test g3, feat g3, feat g4 [, ...]`: reset the
  unit's branch to the group's previous `feat:` (group 3's `feat:`), cherry-pick the empty marked `test:` of group 4 with `git cherry-pick --allow-empty`
  (or re-make it with the `Unit:` and `Already-built: yes` trailers), then cherry-pick the real `feat:` of group 4, and push with `--force-with-lease`. The new
  stop message names the stray `feat:` so the person knows which commit to move.
- **The mixed unit** where an earlier group is built and a later one needs work (group 1 built elsewhere, group 2 needs work): the branch holds no commit at
  group 1, nothing is recorded, as before.
- **A stray `feat:` is not repaired by the build**: the build never reorders or rewrites commits.
- **Skipping the tests agent's model call** for a group whose tests exist: the agent still runs and commits nothing.
- **The push gate, `check_structure`, `group_progress`'s matching rule and restack**: no change except the new field the stop message reads.
