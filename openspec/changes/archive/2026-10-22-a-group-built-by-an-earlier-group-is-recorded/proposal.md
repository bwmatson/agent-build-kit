## Why

Code at agent-build-kit `origin/main` (95f59753).

With `builders.per_group_commits` on, the build counts `test:`/`feat:` pairs on the branch after every group (`Nodes.settle_group`,
`src/agent_build_kit/graph/nodes.py:1443-1459`, called from `implement` at `1503-1508` and from the test-only `stub_checks` advance at `1361-1365`). `unpaired`
(`1430-1441`) reads `group_progress` (`pipeline/commit_order.py:155-174`), which walks the groups in order and takes, for each, a `test:` then a `feat:`
subject with the group's title from the front of the branch. The merged change `a-group-already-built-is-satisfied-in-a-stubbed-build` made `settle_group`
skip the count when `branch_commits == 0` (`1449`), so a unit whose every group is built elsewhere ends `satisfied`.

That does not cover a unit that has commits. On 2026-10-21 `reviewers-are-told-where-to-look/4` (groups 3 and 4) failed again: group 3's builder
implemented group 4's work too (the Start here section, its never-shrinking, the held-unit case; commits `94eb92dc` and `0ccd6540` in the unit's worktree),
so the unit made a real pair for group 3 and the group 4 agents answered "Nothing needed changing. The four tests already pass". `r.commit` found nothing
staged (`wiring.py:860-861`, "an empty commit would be a lie") and made no commit; `settle_group` then had `commits > 0` and `unpaired` named group 4.

What the rest of the system does with a commit that holds no file was read in code:

- **Commit order** (`commit_order.check_structure`, `252-272`): `_files_in` of an empty commit is empty, `classify_paths` returns `{}`, so its kind is `docs`
  (`272`). `substantive` (`274`) leaves docs out, so the first-commit rule (`284`), the "no implementation commit" rule (`294`) and the "two tests commits in
  a row" rule (`297-305`) never see an empty commit. `_pair_problems` (`199-220`) reads subjects only, so `test: T` then `feat: T` pairs, empty or not.
- **Push gate** (`pipeline/gate.py:66-155`): `_tests_commits` (`50-58`) keeps a commit only when `_test_files_in` is non-empty, so the empty `test:` commit
  is not in the list and is never lint-checked or red-run; and if it were, `if not files: continue` (`123-124`) skips it. The stub rule ("a tests commit
  may carry stubs and nothing else") only looks at code paths of a commit that also has tests, of which there are none.
- **The `Unit:` trailer** is read from the tip commit by `unit_groups` (`cli/pipeline.py:6390-6399`, `git log -1 --format=%(trailers:key=Unit,...)`) to give
  the gate the unit's groups. The tip of a branch that ends with an empty `feat:` is that commit, so it must carry the trailer. The `commit` closure puts it
  there (`wiring.py:841-844`) but refuses to commit nothing, so a new empty-commit path is needed.
- **Restack** (`pipeline/restack.py:465-472`) is `git rebase --onto <new> <old> [branch]` with the default `--empty`. A commit that starts empty is kept by
  `git rebase` (verified on git 2.34.1: a branch of four commits, the last two `--allow-empty`, rebased onto a moved `main`, kept all four with subjects and
  trailers intact). Only a commit that becomes empty in the rebase is dropped, and that is the existing behaviour, unchanged. The host-adoption replay already
  uses `cherry-pick --allow-empty` (`restack.py:783`).
- **Commit hooks**: the commit runs with the repo's hooks on, as every pipeline commit does. A pre-commit hook has no staged file to look at, so it has nothing
  to reject; the gate callback `gate(cwd)` of the `commit` closure runs on a staged tree (`wiring.py:862-864`) and has none here. The policy hook refuses
  agent commands, not the pipeline's.

## What Changes

- **A group whose work is already built is recorded with an empty, marked pair.** In a stubbed build, when a group's tests and implementation steps leave
  nothing to commit (the head is where the group began and the commit step staged nothing), the group has neither of its commits, and the branch already
  holds at least one commit, the build checks the tree and, on a pass, makes two commits with `git commit --allow-empty`: `test: <group title>` and
  `feat: <group title>`. Each has the group's usual body sentence, the group's "Done when", and the trailers `Unit: <id>` and `Already-built: yes`. The
  `feat:` body also holds the implementation agent's last message, redacted and cut, under "Already built, the builder's account:".
- **The safeguard is the whole-repository unit tests.** The pair is recorded only when `run_unit_test(whole_repo=True)` passes on the tree, the check that
  ends a unit `satisfied`. It is the only check that runs the tests already on the base (a diff-scoped run would not reach them). When it fails, the unit
  stops with the existing pair message, the output is saved as feedback with the source `unit-test` and nothing is recorded, so a forgotten implementation is
  still caught.
- **A test-only group** (`[e2e-test]`, no `feat:`) that is already built gets only the empty `test:` commit, under the same safeguard.
- **A group with a real `test:` commit and no `feat:` is not touched.** Stubs with tests and no implementation after them still stop the unit, except for the
  one case of a resume: the tip is a marked empty `test:` commit of this group (the run was killed between the two empty commits), when only the
  `feat:` is recorded.
- **The commit trailer** `Already-built: yes` marks both commits. A reader (`commit_order.recorded_built`) answers whether a commit is marked and empty.
- **The zero-commit route is unchanged**: with no commit on the branch, `settle_group` skips the count and the unit ends `satisfied`, as the merged change
  made it. An empty pair is never the first commit of a branch.
- **The setting off is untouched**; the change is inside the stubbed branch of `implement` and of the test-only `stub_checks`.
- **Docs and changelog.** `docs/architecture.md` (the stubbed build paragraph) and `docs/unit-graph.md` (the `implement` row and the `stub_checks` edge) say
  so; one changelog bullet.

## Impact

A unit whose later group was built by an earlier group's builder passes the stubbed build, shows an empty pair for the group in its commit list with the
reason, and goes on to checks and review. The merged change's test of "a third implementation that made no commit" (`tests/graph/test_per_group_partial_commits.py`)
no longer stops the unit unless the unit tests fail; it is rewritten. A reviewer who reads the commits sees `test: <title>` and `feat: <title>` with no
files, `Already-built: yes` and the account. In the squash merge the pull request becomes one commit, so the empty commits vanish from the main branch's
history; the commit message the host proposes for the squash is the host's to compose and not changed here.

## Not in this change

- **A mixed unit with the built group first** (group 1 built elsewhere, group 2 needing work). At group 1 the branch has no commit yet, so nothing is
  recorded (the zero-commit skip stays); the unit stops after the last group, naming group 1, as the merged change left it. Recording a pair later than its
  position would need the build to match groups other than by position.
- **Skipping the agent calls** for an already-built group: both agents still run and commit nothing.
- **A restack change.** Git keeps a commit that starts empty; a test pins that. `--empty=keep` is not added, because it would also keep commits that
  become empty by duplication, changing the restack.
- **The `adapt` port after a restack conflict** rebuilds the branch's work from the model's port and is outside the per-group pairs already.
- **The push gate, `check_structure`, `group_progress`, `unpaired` and `satisfied`**: none changes.
