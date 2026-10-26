## Context

Code at agent-build-kit `origin/main` (e9a94029). Read first: the archived change `a-group-built-by-an-earlier-group-is-recorded` and its main spec
`built-group-recorded-as-empty-pair`. This change adds a write (an empty `test:`, and an empty `feat:` after a real `test:`) and a message; it changes no
matching rule.

Flow for one group of a stubbed unit today: `tests` (`src/agent_build_kit/graph/nodes.py:~1360-1392`) runs the tests agent and commits nothing; `stub_checks`
(`1416-1439`) runs the static checks and, once they pass, `made = r.commit(self.message(TESTS_PREFIX, True, state), cwd=tree, base=ref)` (`1426`) commits
`test:` if anything is staged, then `done = {"head": r.head(tree), ...}` (`1427`); for a group that is not test-only it returns `{**done, "test_only_done":
False}` (`1429-1430`). `implement` (`1615-1665`) skips its agent when the head has moved since the group began, unless `half_recorded` (`1619-1622`), runs the
agent, commits `feat:` (`1651`), calls `record_built(state, ref, made, account)` (`1652`) and then `settle_group` (`1662`).

## Decisions

### Rule 1: the empty marked `test:` is made in `stub_checks`

- **Where.** In `stub_checks`, after `check_loop.check_round` has returned ok (`1422-1424`), after `made = r.commit(...)` (`1426`) and before the
  `return {**done, "test_only_done": False}` at `1430`. A new node method (named `record_no_new_tests`) decides and records; `stub_checks` calls it only in the
  not-test-only branch (`step is None or not step.test_only`), and the `done["head"]` update is read AFTER the empty commit
  (`done["head"] = r.head(tree)`), so `state.head` is the empty `test:`'s hash. That ordering matters: `implement` compares `r.head(tree) != state.head` (`1619`) to
  decide whether the implementation commit is "already on the branch"; with the head read before the empty commit, `implement` would skip its agent. With it read
  after, a fresh run's head equals `state.head` and the agent runs; a resumed run is covered by `half_recorded` (below).
- **Conditions** (all of): the build is stubbed and the group is not test-only (`group_step(state)` exists and `not step.test_only`); `made == 0`; the branch holds
  at least one commit of its own (`r.branch_commits(tree, ref) > 0`, which leaves the zero-commit route to `satisfied` alone); `progress.done == state.group` for
  `progress = self.branch_progress(ref)` (the earlier groups all have their pairs, and the walk has not already passed this group); `progress.tests_made` is false (no
  `test:` of this group yet); and no lone `feat:` of this group sits where its `test:` should be (see "The stop message"). A group whose tests agent committed
  (`made > 0`), a test-only group (its path is unchanged, `1431-1439`), and the old non-stubbed build (`group_step` is None) record nothing here.
- **Commit.** `r.commit_built(message, cwd=tree)` (`wiring.py:922-943`): `git commit --allow-empty`, hooks on, no gate, one attempt, trailers `Unit:`,
  `Adopted-From:` (when set) and `Already-built: yes` last. The message is `self.message(TESTS_PREFIX, True, state)` (subject `test: <group title>` plus the
  group's usual body) followed by one paragraph: `This group adds no new tests: the tests it needs already exist on the branch.` No account from the tests agent is
  added (its account is not kept for a group that is not test-only, `1388`). No model call, no test run: the commit claims only that the group adds no new tests. A
  hook that rejects it raises `CommitRejected`, as `commit_built` does today.
- **What follows.**
  - The implement agent **changes something**: `implement` commits `feat:` through `r.commit` (`1651`), `made > 0`, `record_built` returns None (`1562`), and
    `settle_group` finds `test: <title>` (empty, marked) then `feat: <title>` (real): `group_progress` (`commit_order.py:162-181`) counts the group done. The result
    is a pair, `test` empty and `feat` real. This is the incident's case.
  - The implement agent **changes nothing**: `made == 0`, `half_recorded` (`1525-1533`) is true (`progress.done == state.group`, `progress.tests_made` is true, and the
    tip is a marked empty commit by `recorded_built`, `commit_order.py:138-144`), `resumed` is true in `record_built`, so it skips the `test:` (`1584`), runs
    `run_unit_test(whole_repo=True)` and, on a pass, records only the empty `feat:` with the agent's account (`1586-1589`). The result is the same two-commit shape as
    the merged change's empty pair. On a failure it stops with the pair message and `unit-test` feedback (`1578-1581`), and the empty `test:` stays on the branch; a
    requeue resumes at `implement` (below), as after a kill.
- **Resume after a kill between the empty `test:` and the implement step.** The branch tip is the marked empty `test: <title>`, so `resumed` (`1141-1154`) reads
  `progress.done == the group`, `tests_made` true and sets `resume = RESUME_IMPLEMENT`; `prepare` goes to `implement`; `half_recorded` is true so the head having moved
  does not skip the agent (`1619-1622`); the two outcomes above follow. A kill before the empty `test:` repeats the group's tests step (the agent finds the tests
  present and commits nothing, the static check passes, the empty `test:` is made).
- **Rejected alternatives**: teaching `group_progress` that a group may lack a `test:` (four readers of the order would change and could disagree: `group_progress`,
  `unpaired`, resume and the gate's `_pair_problems` at `commit_order.py:206-227`); recording the empty `test:` in `implement` after the agent ran (the order of
  the commits would depend on whether the agent changed files, and a kill in between would leave the lone `feat:` the incident shows); making the empty `test:` when
  the tests agent committed nothing and the head moved (not needed; `made == 0` is the one signal).

### Rule 2: real tests that already pass, and an implement step that changes nothing

- **The case.** The group has a real `test:` commit (`made > 0` at the tests step, so no empty `test:` was made), the implement step commits nothing (`made == 0`
  at `1651`, `r.head(tree) == state.head`), and the whole-repository unit tests pass. Today `record_built` returns None at `if progress.tests_made and not
  resumed: return None` (`1568-1569`), so `settle_group` stops the unit with the pair message. Incident: `a-unit-over-its-tier-is-held-and-split/13`, group 12 (real
  `test:` commit `eed46f86`; "The five group 12 tests pass without any source change").
- **The change.** That early return is replaced: a `tests_made` group whose tip is NOT a marked empty commit (a real `test:` tip) is no longer excused or refused by
  shape; it goes through the same safeguard as every other recorded group. `record_built` runs `run_unit_test(cwd=tree, base=ref, whole_repo=True)` (`1575`); on a pass
  it records only the empty `feat:` (no `test:` is made, as for `resumed`), and the body of that `feat:` holds, before the agent's account, one paragraph:
  `The tests for this group pass without further implementation: the implementation already exists.` On a failure (or a flake finding, `1576-1577`, or a broken
  environment, `1572-1573`) it behaves as today: `failed_unit_test`, `stop(...)` with the pair message `the branch holds no tests and implementation pair for group
  <n> (<title>)` (`unpaired` returns the pair text when `tests_made` is true, `1509-1512`). Nothing is recorded on a failure.
- **Why the whole-suite pass is the discriminator.** The whole-repository run includes the group's new tests. If the tests pass, every behaviour they check already
  exists, so "tests already green because the implementation exists" holds. If the tests are stubs that raise `NotImplementedError` until implemented
  (what the stubbed build asks a tests agent to write), the run fails and the unit stops: that is exactly the "stubs and tests with no implementation" case the pair
  rule exists to catch, and it is still caught. A test-only group never reaches this path (it has no `feat:`).
- **Conditions** (all of): stubbed, not test-only; `made == 0` from the implementation commit step; `branch_commits > 0` (true: the real `test:` is a commit);
  `progress.done == state.group`; `progress.tests_made` true; the head unmoved since the group's tests step (`r.head(tree) == state.head`, kept) or the half-recorded
  resume. A real `test:` with an implementation that changed files is unchanged: `made > 0`, normal `feat:`.
- **The push gate does not block a green real `test:`.** The gate's "red" expectation for a tests commit (`gate.py:11`, `red_check`; the red run at `135-143`) is
  evaluated by `check_branch`, which is called from exactly two places: `cmd_gate` (`src/agent_build_kit/cli/pipeline.py:7327`, the `abk gate` command, run by a person
  or a hook) and the module's own `main` (`gate.py:167`). Neither the build nodes nor the runner's push path calls it (re-verified by `git grep 'check_branch('` on
  origin/main: only those). The pipeline's own push condition is the approved-SHA check. So a green real `test:` followed by an empty `feat:` does not stop the push.
  A person who runs `abk gate` on such a branch will see the red check report the tests commit as not failing; that is the command-form's existing view of a
  tests commit that does not fail, it is not changed here, and the reviewer judges the commit list and the reason in the `feat:` body.
- **Reviewer view.** The commit list shows `test: <title>` with files, then `feat: <title>` with no file, `Already-built: yes`, and a body holding the sentence above and the
  agent's account (redacted, cut to 2,000 characters as today).

### The stop message for a lone `feat:`

- `GroupProgress` (`commit_order.py:155-160`) gains a field `lone_feat: str` ("" by default): when the walk stops because the subject at the group's `test:` position is
  `feat: <that group's title>` (`172-174`), it holds that subject. `unpaired` (`nodes.py:1502-1512`) returns, for a non-test-only group with `lone_feat` set, the text
  `a feat: commit for group <n> has no test: commit before it (<subject>)` and `settle_group`/`record_built` stop with it **without** the prefix `the branch holds no `
  (the stop is exactly that sentence). For example: `a feat: commit for group 4 has no test: commit before it (feat: The Start here section is never shrunk)`.
  Every other missing-pair stop keeps today's text.
- **Rule 1 does not record when `lone_feat` is set.** The branch of the incident (`test g3, feat g3, feat g4`) already carries the stray; an empty `test:` after it would
  not mend the order. So `stub_checks` makes no empty `test:`, the implement step runs, and `settle_group` stops with the new message. A person repairs it (below).

### What stays the same

- **Push gate** (`pipeline/gate.py`, `commit_order.check_structure`): the empty `test:` is `docs` kind (no file), so the first-commit rule needs the first substantive
  commit (an earlier group's real `test:`) and finds it, the "two tests commits in a row" rule ignores it, `_pair_problems` pairs the subjects, and `_tests_commits` leaves it
  out, so it is neither lint-checked nor red-run. Pinned by a test over a temporary git repository (empty marked `test:` then a real `feat:`, and the real `test:` then an
  empty `feat:`). A branch whose commits are all empty is still refused ("the branch changes no tests and no code"), and Rule 1 requires a commit of the branch's own.
- **Restack**: `git rebase --onto` keeps a commit that starts empty; the empty `test:` keeps its subject and trailers, so position and title matching still holds
  (a test uses `move_branch_onto` as `tests/pipeline/test_restack.py`-style temporary repositories do). No `--empty=keep`. The squash merge drops the empty commits.
- **Zero-commit route, test-only groups, the old build, the whole-suite safeguard for the empty `feat:`**: as the merged change left them.

## Risks

- **A hidden gap**: the empty `test:` says "no new tests" without checking that the existing tests cover the group; as in the merged change, the whole-suite pass is
  the only evidence and the reviewer reads the commit list. The empty `feat:` for real, passing tests carries the same risk: a test that passes for the wrong reason.
- **A requeue after the whole-suite failure** now starts from a marked empty `test:` tip (Rule 1) or a real `test:` tip (Rule 2) and resumes at `implement`, which
  re-runs the agent; before, a Rule 1 failure left no commit and resumed at `tests`. Accepted: no work is lost and the order stays valid.
- **Cost**: unchanged: one whole-suite run per recorded `feat:`; the empty `test:` runs nothing.
