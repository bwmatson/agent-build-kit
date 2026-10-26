## Context

Code at agent-build-kit `origin/main` (23ec1741). Read the proposal first: it lists what the two loops, the profiles and the commit path do today, with file and line.
The failure that prompted this was a formatter hook repairing a file during the stub loop's check run; the fix agent had nothing left to edit and the "changed nothing" stop failed
the unit. The decisions below remove the cause (formatters run before the commit, by the pipeline) and the duplication (one routine for both loops).

## Decisions

### 1. The profile method: `fix_command(files)`

- **Shape.** `ToolchainProfile.fix_command(files: list[str]) -> list[str] | None`, declared in `profiles/base.py` beside `clean_command` and `lint_command`. `files` are the unit's changed and untracked
  files of one project, relative to that project's directory (the same convention as `lint_command` and `clean_command`, which run in the project's directory). It returns one argv, run with the files
  already in it, or None when none of the files is one the profile fixes. It is read tolerantly, as `supports_stubs` is (`base.py:90-93`): the runner uses `getattr(profile, "fix_command", None)`, so a
  third-party profile without it gets no fixer pass and builds as today. Nothing else about a profile changes, and a profile written before this change keeps loading.
- **python-uv** (`profiles/python_uv.py`): `["uv", "run", "pre-commit", "run", "--files", *files]`, every file. The hooks are what edit files (the formatter, the end-of-file and whitespace fixers,
  `ruff check --fix` where the repo's hook has it), and the repo's own hooks stay the authority, so the profile names no tool. Exit status is ignored (a hook that edited a file exits 1). A type-checker hook
  may fail, and its failure is also ignored here: the checks decide.
- **node-npm** (`profiles/node_npm.py`): `["sh", "-c", 'npx oxfmt "$@"; npx oxlint --fix "$@"', "sh", *sources]`, where `sources` are the files with an extension of `_SOURCE` (`node_npm.py:45`); None when there are
  none. `oxfmt` with no `--check` writes the format; `oxlint --fix` applies the fixable lint findings; `tsc` is not fixable and is left to the agent and the check. The `;` matters: `oxlint` exits 1 for an unfixable finding
  and the formatter pass has already run. **The file selection does not reuse `_DIFF`.** `_DIFF` is `git diff ... "$1...HEAD"`, a committed range, and a fixer before a commit has to reach the uncommitted and untracked
  files. What is reused is the extension list `_SOURCE`, so `lint_command`'s idea of "a source file" and the fixer's agree. A node workspace's per-project subdirectories are handled by the runner (below), as
  `build_stub_checks` handles them for `clean_command` (`wiring.py:942-968`, `config.by_project`): the command runs in `cwd / owner.prefix`, with paths relative to it.
- A repo's own command replaces the profile's (decision 5), so a repo with a non-standard formatter is not stuck with the profile's choice.

### 2. Which files, and where the fixers run from

- **The unit's files are the working tree's uncommitted changes**: modified, added, renamed (new name) and untracked files, from `git status --porcelain -z` run in the worktree, deletions left out. Before any commit
  the pipeline makes, everything already committed has been through the fixers (it passed through this step before its own commit) or is the base's, so the uncommitted set is the unit's own change to be
  committed next. It is the same set `r.commit` is about to `git add -A`, less the lock files and artifacts that `commit` unstages (`restore_unchanged_locks`, `unstage_untracked_locks`, `unstage_artifacts`
  in `wiring.py:849-915`): those are filtered the same way, so a fixer never rewrites a lock file the commit then discards. Nothing outside it is ever passed: no repo-wide run, no file of the base.
- **Per project.** The files are grouped with `config.by_project(repo.projects, names)` (`config.py:1055`), each group run with `profiles.for_project(owner, repo_profile)` in `cwd / owner.prefix` with the
  paths relative to the project, exactly as `build_stub_checks` runs `clean_command`. A repo with no projects is one group at the root.
- **Protected files are skipped, and the log says so.** A path for which `review_paths.is_protected(active(), repo, path)` (`pipeline/review_paths.py:48`; the path relative to the repo root) is true is
  left out of `files`. A fixer can still reach a protected path that was not passed (a pre-commit hook may rewrite more than it was given): after each pass the runner restores any protected path the pass
  changed to its content before the pass and logs it. The fixers never end a pass leaving a protected file different from how they found it.
- **A repo with nothing changed** runs no command and writes no line.

### 3. The runner function, the passes, the exit status and the log line

- **Where.** `StackRunner.run_fixers: Callable[..., FixResult]`, beside `run_stub_checks` (`stack_runner.py:1531`), with a no-op default (`FixResult()`), built by `wiring.build_fixers(profile=, projects=,
  repo=, run=)` from the same `profile`/`projects` that build `run_stub_checks` (`wiring.py:3840`). `FixResult` is a frozen pydantic model: `changed: tuple[str, ...]`, `skipped: tuple[str, ...]` (protected),
  `failed: tuple[str, ...]` (reasons a command could not run). The node writes the log line from it.
- **Passes.** Per project the command runs up to **two** passes, a second only when the first changed any file (judged by the content digest of the passed files, so a pass that edits nothing ends the run). Two covers
  "the formatter's output feeds a second hook" (a hook that fixes whitespace after the formatter) without a loop. The limit is a constant of the runner and the same for every profile.
- **Exit status is ignored.** A fixer exits non-zero for what it changed (pre-commit) or for what it could not fix (`oxlint`). The runner decides "changed" from the files, not from the status.
- **A fixer that fails to run** (the command cannot start, a missing tool, a hook crash) is logged, `FixResult.failed` carries the reason, and the build goes on: the check still decides, because anything the fixer would
  have repaired still fails the check, and an agent then sees the failure as today. A failed run never stops a unit and never counts as a fix round.
- **The log line**, written by the node through `self.say` once per call that did anything: `fixers changed 2 file(s): a/b.py, c.py`, or `fixers changed nothing` when files were passed and no pass changed one,
  and, when they apply, `fixers skipped protected: <paths>` and `fixers could not run: <command>: <reason>`. No model call is made and no usage is recorded.

### 4. Where the fixers run

`Nodes.apply_fixers(state)` calls `r.run_fixers(cwd=tree, ...)`, writes the log line, and is called at five places:

| Where | Before | Why there |
|---|---|---|
| `stub_checks` (stubbed build) | the static check, so before the tests commit | the check must see the formatted tree, and the commit follows the pass |
| `implement` (`1587`) | `r.commit(CODE_PREFIX ...)` (`1621`) | what is committed is formatted; the agent's step has just ended |
| the checks loop's fix step | `r.commit("fix: ... (checks, round N)")` (`1756`) | the check runs on the committed branch, so the commit must be formatted |
| `tests`, old build (`1374`) | `r.commit(TESTS_PREFIX ...)` | same step in a build that is not stubbed |
| `implement`, old build | `r.commit(CODE_PREFIX ...)` | same as the stubbed `implement`; one call site serves both |

The stubbed `tests` node commits nothing (`1370-1373`), so it needs no call: its commit is `stub_checks`'s. The call in `implement` is before `record_built` (`1622`) and `settle_group`; a clean tree runs nothing, so
the already-built route is unchanged. A unit that resumes on a commit already made (`r.head(tree) != state.head`) skips its agent and its commit and therefore its fixers, as today.
The pipeline's commit gate (`commit-gate`: retry once when a hook rewrote a staged file, then the author agent) stays as the backstop for anything the fixers did not reach.
`fixers` run once per call, not per attempt of `r.commit`.

### 5. The repo's own fix command

- **Setting:** `repos.<name>.tests.fix_command`, an optional list of strings on `TestsConfig` (`config.py:911`), where a repo's `tests` already holds its test-time facts (markers, splits, `root_extras`). Unset (None) means "the profile's
  `fix_command`"; a non-empty list is an argv to which the project-relative file names are appended and which runs in the project's directory; an empty list `[]` turns the fixer pass off for the repo.
  It is read where `run_fixers` is built, from the repo config, with no new global limit.
- **Policy, not machine.** It lives in `abk.yaml`: it names the repo's own tooling and reads the same on every machine that runs the pipeline (the `abk-config` skill's "would this be wrong on another person's
  machine?" test: no). It goes in `abk.local.yaml` only for a person's one-machine experiment, which the merge supports like any key.
- **The `abk-config` skill** documents it under the repo's `tests` block, and `abk config --show` prints it; `abk doctor` needs no check (an unusable command is logged at run time and ignored, per decision 3).

### 6. The shared check-and-fix helper

- **Where.** A module `graph/check_loop.py`: a frozen pydantic model `CheckLoop` for the per-loop parameters, and two functions, `check_round(nodes, state, loop)` and `fix_round(nodes, state, loop)`, which
  `Nodes.stub_checks`/`checks` and `Nodes.fix_stub_checks`/`fix_checks` call. The graph keeps its four nodes and its routes (`ROUTES`, `2989-3010`, `after_stub_checks` etc.): the loop is a graph cycle,
  and a helper cannot swallow the two nodes without changing the routes, the checkpoints and the resume (`after_prepare` goes to `FIX_STUB_CHECKS` when `state.stub_loop`). What is shared is what each node did.
- **Parameters of `CheckLoop`:**
  - `check: Callable[[], tuple[bool, str]]`. The stub loop passes the static checks (`r.run_stub_checks(cwd=tree)`: lint, format, types, no test, since the tests are expected to fail until implemented); the
    checks loop passes the unit-test run (`r.run_unit_test(cwd=tree, base=ref, whole_repo=False, **answering)` with its selection of the tests the unit touched and the whole-suite run where required). The helper knows nothing
    about tests. The callable may raise `CheckParked(update)` for the one case that is not a pass or a failure (a flake the unit waits on: `wait_for_fix`, `1655`), and the helper returns that update unchanged.
    The environment and worktree-fault blocks (`1642-1647`) stay in `checks` ahead of the call.
  - `source: FeedbackSource` and `heading: str`: where a failure is saved (`STUB_CHECKS` with no heading, `UNIT_TEST` with `UNIT_TEST_FAILED`).
  - `rounds: str`: the state field the loop counts in, `stub_rounds` or `fix_rounds`; and `rounds_after(n)`, which names the update (`{"stub_rounds": n}` or `{"fix_rounds": n, "head": ...}`).
  - `prompt: Callable[[str], str]` (and an optional `follow_up`): the fix prompt for a feedback text, `STUB_CHECKS_PROMPT` or `CHECKS_PROMPT`/`CHECKS_CONTINUATION` with the node's own extras.
  - `commit: str | None`: the commit rule. `None` for the stub loop (**no `fix:` commit**: the tests commit follows the pass, as today), and `"fix: {title} (checks, round {n})"` for the checks loop.
  - `label`, `spent_message(budget)`, `unchanged_message(n)`: the text of the two stops, which are exactly today's four strings.
- **What `check_round` does**, in this order: (a) for a loop with `commit is None`, run the fixers (decision 4), so the check sees the formatted tree; (b) run `check`; (c) on a pass clear the saved feedback of
  this source when a round was spent, and return `{"ok": True}` to the caller, which adds what is its own (the stub loop's commit and `stub_loop`/`test_only_done` fields, the checks loop's `checks_ok` and `head`);
  (d) on a failure `say` the output, call the loop's `on_failure(output, round)` (`record_check_failure` for the checks loop), save the feedback under `source` *before* anything can stop the run, and stop with
  `spent_message` when `out_of_rounds(state-count)` says the rounds are spent.
- **What `fix_round` does**: take the digest `(r.head(tree), r.tree_state(tree))`; run the agent with `prompt(feedback)`, the redacted saved feedback and the build model; for a loop with a `commit`, run the fixers and then
  `r.commit(...)`; compare the digest again and stop with `unchanged_message(n)` when it is the same; else return the new count. The checks loop's "fix round already on the branch" case (`r.head(tree) != state.head`,
  `1729`) is kept: the helper skips the agent when the caller says the round is already done.
- **The counter** is the caller's choice through `rounds`; `out_of_rounds` (`2772`) and `max_check_rounds` are unchanged, and a loop's counter is reset as today (`stub_rounds` to 0 on a pass at `1397`; `fix_rounds` by review at
  `1816`, `1870`...).
- **The commit rule and "changed nothing" together.** The stub loop's change test was the tree digest; the checks loop's was HEAD. The helper's digest is the pair, which gives the same answer in both: for the stub loop (no commit)
  the head cannot move, so it is the tree; for the checks loop a fix commit moves HEAD, and an agent that commits on its own moves HEAD too. A fixer-only change before the commit makes a real `fix:` commit
  and counts as a change: the next check then decides, which is the intent.
- **The stop rule is kept, not relaxed.** Today it is wrong in one case: a hook that repairs a file during the check run leaves the agent nothing to change although the checks would now pass. Decision 4 removes the case,
  because the fixers run before the check (stub loop) and before every commit (checks loop), so a formatter's edit is never made *by the check*. What reaches the stop is a round where the agent changed nothing and the
  check still fails, which is the stop's purpose. A later change can revisit the rule if another case shows up (for instance a check that is flaky in the tree it checks).
- **Not a new abstraction for the sake of it.** The two bodies are the same sequence with five differences, and the differences are the parameters above. A test asserts that each node delegates, so the duplication cannot grow back.

## Order of the change

Groups 1 (profile method, runner, setting), 2 (the helper, a refactor with no behaviour change) and 3 (the fixers' call sites) are separate units because 2 can be reviewed as a pure refactor and 3 as the behaviour change. Group 3 depends on 1 and 2.

## Risks

- **A fixer that rewrites something the agent wrote on purpose** (a hand-aligned table). The repo's own hooks do this already when the commit gate runs them; the fixers only run them earlier. A repo that does not want it sets `fix_command: []`.
- **A pre-commit hook run with `--files` differs from `--from-ref/--to-ref`.** A hook with `pass_filenames: false` runs over the repo whatever `--files` says, so it can touch other files. The protected-path restore (decision 2)
  covers the policy; a hook touching ordinary files outside the unit shows up in the diff a reviewer reads, as any hook run would.
- **Cost.** One pre-commit run (two when it changes something) per commit, no model call. Accepted: it replaces a fix round of an agent.
- **A dirty tree no commit follows.** The fixers run before commits only; a stubbed `tests` step that ends without a commit does not run them (its commit is `stub_checks`'s).
