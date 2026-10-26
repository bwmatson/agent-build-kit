## Context

Code at agent-build-kit `origin/main` (95f59753). Read first: the merged change `a-group-already-built-is-satisfied-in-a-stubbed-build` (archive) and
`a-test-only-group-commits-no-pair`. The proposal lists what the pair count, the gate, the trailer reader and git rebase do with a commit that holds no
file.

Flow today for one group of a stubbed unit: `tests` runs the tests agent and commits nothing (`1330-1332`), `stub_checks` (`1344-1373`) runs lint, format and
types and commits `test:` if anything is staged, `implement` (`1466-1509`) runs the implementation agent, commits `feat:` if anything is staged and calls
`settle_group(state, ref, commits)`, which stops on a missing pair or advances `group`/`more_groups`. `state.head` is the head when the group's tests step
ended (`1334`, `1356`); `implement` skips its agent when the head has moved since (`1470`).

## Decisions

- **Record the group; do not change what the build requires.** The stubbed build matches commits to groups by position and title in four places
  (`group_progress`, `unpaired`, resume via `resumed` at `1083`, and the push gate through `check_structure`). Teaching each of them a new way to say "this
  group has no commits" would be four changes with four chances to disagree. An empty commit pair with the group's own subjects satisfies all four as they are,
  so the change adds a write, not a reading rule. Rejected: matching by a trailer on a later commit (the position rule is what also tells two groups with
  one title apart); recording the group in the pull-request body (no commit-order meaning); a sentinel file in the tree (a file is a diff for the reviewer to
  read and the push gate would classify it).
- **Empty commits through a new runner method, `commit_built(message, cwd)`.** The `commit` closure (`wiring.py:838-880`) is a "nothing staged: no commit"
  function and stays so, since an empty commit there is a bug. The new method sits beside it, builds the same trailer block (`Unit:`, `Adopted-From:`) plus
  `Already-built: yes`, and runs `git commit -q --allow-empty -m <body>` with the hooks on and without `gate`. It returns after one attempt; a hook that
  rejects an empty commit raises `CommitRejected` (not retried or handed to `fix`: there is nothing for an agent to change). The message is subject, body
  paragraphs, then the trailer block last, so `%(trailers)` reads `Unit` from the tip, which the push gate needs (`cli/pipeline.py:6390`).
- **The trailer is `Already-built: yes`.** A key a reader can grep and `git log --format=%(trailers:key=Already-built)` can print; `yes` is the only value
  written. `commit_order.recorded_built(repo, sha)` returns true when a commit has the trailer and no changed file; the node reads it only for the resume
  case. A hand-made commit with the trailer and a file is not "recorded built": the file test keeps the marker from excusing real work.
- **Condition for recording** (all of): the build is stubbed; `group_progress(subjects).done == state.group` and `tests_made` is false (the branch holds
  neither commit of this group); `r.head(tree) == state.head` after the implement step and its commit step staged nothing (the agent neither committed nor left
  files: "the tree is clean", judged by the same commit step that decides everything else, so lock files and artifacts it filters out do not make a clean
  tree dirty); and `branch_commits(tree, ref) > 0`. The last is what leaves the zero-commit route alone: with no commit the existing skip applies and the unit is
  satisfied.
  - **Resume case**: `tests_made` is true and the tip is a marked empty `test:` commit with this group's title (`recorded_built`). Then only the `feat:` is
    recorded, after the same safeguard. A real `test:` commit with no `feat:` is never excused: stubs and tests with no implementation after them are exactly
    what the pair rule exists to catch.
- **The safeguard is `run_unit_test(whole_repo=True)`, once per recorded group.** It is what ends a unit `satisfied` and what judges a branch with no diff.
  A diff-scoped run (`whole_repo=False`) would run only members the branch's own commits touch and would not run the tests of a group built by the base or
  by an earlier group's unit, so a forgotten implementation would pass it. The cost is a full suite per already-built group; the case is rare, and an
  affected-tests selection is not used (a pass must not depend on a selection). On failure `implement` calls `stop(...)` with the pair message
  (`the branch holds no tests and implementation pair for group <n> (<title>)`), saves the output as feedback with `FeedbackSource.UNIT_TEST` and writes it
  to the log, as the `unit_test` node does. A flake finding (`FlakeFound`) counts as a failure here: nothing is parked for a group's record.
  Environment faults take the `unit_test` node's `blocked` route (`environment_problem`), so a broken toolchain is not read as "the work is missing".
  Judging the tree before recording means the empty commits are never a claim the build has not checked.
- **The reason is the agent's account.** `self.agent(...)` returns the run's final message (`613-646`); the implementation step's is kept, passed through
  `redact_text`, cut to 2,000 characters and written under "Already built, the builder's account:" in the `feat:` body. The tests agent's message is not kept.
  On the resume case the implementation agent has run again (the head equals `state.head`), so the account is that run's. A reviewer reads it from the commit
  list; `git log` shows it. Nothing else is stored.
- **Order of the two commits and the failure window.** `test:` is committed first, then `feat:`; a kill between them leaves a marked empty `test:` tip, which
  `resumed` (`1083-1099`) reads as `tests_made`, so `prepare` goes to `implement` (`RESUME_IMPLEMENT`) and the resume case above completes the pair. A kill
  before the first commit repeats the group from its tests, as any group does. A kill after both leaves the group done.
- **The pair count runs after the record.** `settle_group` is called as now; with the pair in place `unpaired` returns "" for this group, so the count
  passes and the group advances. `produced_nothing` is `branch_commits == 0` after the record, i.e. false.
- **Test-only group**: `stub_checks` (`1357-1365`) is the advance. When the group is test-only, its stub-check commit staged nothing, the head is unmoved and
  the branch holds commits, the same safeguard runs and only the empty `test:` is recorded (no `feat:`, matching what the group is). `group_progress` counts the
  group done at that commit; the gate's `_test_only_commits` flags it by subject and nothing in it is a test file. Same marker, same account in the body
  (the tests agent's message here).
- **Push gate accepts it unchanged** (confirmed in code, to be pinned by a test over a temporary git repo): the empty commits are `docs` kind to
  `check_structure`, so the first-commit rule needs the first substantive commit (group 3's real `test:`) and finds it; `_pair_problems` pairs the subjects;
  `_tests_commits` ignores the empty `test:` so no clean or red run is made for it; `unit_groups` reads the `Unit` trailer from the empty `feat:` tip. No
  change in `gate.py` or `commit_order.py` is made except the new reader. A branch whose only commits are empty ones is refused by the existing "the branch
  changes no tests and no code" rule; recording is never the first commit, so the build cannot produce one.
- **Restack**: `git rebase --onto` keeps a commit that starts empty by default (verified, git 2.34.1; documented as `--keep-empty` being the default of the
  merge backend), so the pair rides along, subjects and trailers intact, and position and title matching still holds. Not added: `--empty=keep`, which would
  also keep a commit that turns empty because the new base already carries its change; that drop is a feature of the existing restack, and an empty commit that
  was recorded is empty already. The host-adoption replay already uses `cherry-pick --allow-empty` (`restack.py:783`). If the new base already holds group
  3's real pair, those commits drop as today and the empty pair of group 4 remains, and the position walk then fails for the whole branch, as it already does
  for any partly dropped branch; the restack then goes the way it goes now (the `adapt` port when the checks are not met).
- **Squash merge**: the pull request is squashed into one commit; the empty commits and their trailers do not appear on the main branch. The reviewer's view
  is the pull request's commit list. The squash message is composed by the host; nothing here edits it.
- **Setting off**: `group_step(state)` is None, so none of this runs; the old build's one `test:`/`feat:` pair and zero-commit route are untouched.

## Risks

- **A hidden gap**: a group whose work is truly missing but whose tests were never written passes the whole-repo run, because nothing tests it. The pair
  records "the tree passes", not "the group is covered". The same risk the merged change took for `satisfied`; the reviewer sees the empty pair and the
  account in the commit list, and the review of the unit judges the whole diff.
- **Cost**: one whole-suite run per recorded group (the unit's `checks` runs the unit tests again later). Accepted; the case is rare.
- **Marker abuse**: an agent cannot write the marker on a file-bearing commit to dodge the rule, as the reader requires no changed file; it cannot commit
  at all in a build run (the policy refuses it).
