## Why

Code at agent-build-kit `origin/main` (23ec1741).

Two loops check a unit's work and hand failures to the builder, and each has its own copy of the logic:

- **The stub loop** (a build with `builders.per_group_commits`, `Nodes.stubbed` `src/agent_build_kit/graph/nodes.py:1582`, `Nodes.stub_checks` `1385-1417`).
  It runs `r.run_stub_checks(cwd=tree)` (`pipeline/wiring.py:942-968`, `build_stub_checks`: `git add -A`, then each owning project's
  `profile.clean_command(types=True)` in the project's directory), and on a pass commits the tests with `r.commit(...)` (`1396`). On a failure it saves the output
  as feedback under `FeedbackSource.STUB_CHECKS` (`1412`), stops when `out_of_rounds(state.stub_rounds)` (`1413`, `2772`) says the rounds are spent, and goes to
  `Nodes.fix_stub_checks` (`1419-1446`). That node takes `before = r.tree_state(tree)` (`1427`), runs the agent with `STUB_CHECKS_PROMPT`
  (`pipeline/stack_runner.py:412`) and stops with "static checks failing and fix round N changed nothing" when `r.tree_state(tree) == before` (`1444-1445`).
  `tree_state` (`wiring.py:971-979`) is `git add -A` and `git write-tree`.
- **The checks loop** (every build, `Nodes.checks` `1637-1683`, `Nodes.fix_checks` `1723-1763`). `checks` runs `r.run_unit_test(..., whole_repo=False)` on the
  committed branch, saves a failure under `FeedbackSource.UNIT_TEST` with the `UNIT_TEST_FAILED` heading (`1670-1672`) and stops when
  `out_of_rounds(state.fix_rounds)` (`1673`). `fix_checks` runs the agent with `CHECKS_PROMPT` (`stack_runner.py:384`), makes `r.commit(f"fix: {unit.title} (checks, round
  {attempt})", ...)` (`1756`) and stops with "checks failing and fix round N changed nothing, before review" when HEAD has not moved (`1757-1760`).

Both stops read "the agent changed nothing" as a failure whether or not the checks would now pass. A hook that repairs a file during the check run leaves the agent
nothing to change, which is the case that failed the unit above. The root cause is that the formatters and auto-fixers run only as part of a check, so a
run that fixes things also fails.

What the profiles and the commit path offer today, read in code:

- `ToolchainProfile` (`profiles/base.py:102-185`) declares `lint_command`, `lint_command_all_files` and `clean_command`; no method applies fixers. `supports_stubs` is
  the precedent for an optional capability: declared by a profile, read with `getattr(profile, "supports_stubs", False) is True` (`base.py:90-93`).
- python-uv (`profiles/python_uv.py:336-351`): `lint_command(base)` is `uv run pre-commit run --from-ref <base> --to-ref HEAD`; `clean_command` is
  `uv run pre-commit run --all-files` (with `types`) or `SKIP=pyrefly-check uv run pre-commit run --all-files`. Hooks (the formatter, end-of-file and whitespace
  fixers, `ruff check --fix` where the repo's hook has it) edit files and exit non-zero when they did. The agent-facing command list already names
  `uv run pre-commit run --files {path}` (`230-234`).
- node-npm (`profiles/node_npm.py`): `lint_command(base)` (`194-197`) is `_DIFF_LINT` (`50-57`), which lists `git diff --relative --diff-filter=d --name-only -z "$1...HEAD" --
  '*.ts' ...` (`_DIFF`, `47-49`, over `_SOURCE = ("ts","tsx","js","jsx","mts")`, `45`) and pipes it to `xargs -0 npx oxlint` and `xargs -0 npx oxfmt --check`;
  `clean_command` (`282-286`) is `npx oxlint . && npx oxfmt --check .` plus `npx tsc --noEmit` with `types`. A workspace's projects are handled by the callers, not by the profile:
  `build_stub_checks` runs each owner project's profile command in `cwd / owner.prefix` over paths made relative by `config.by_project` (`config.py:1055-1067`);
  the profile commands themselves are written relative to the directory they run in. `_DIFF` compares `"$1...HEAD"`, a committed diff, so it cannot see the
  uncommitted and untracked files that a pre-commit fixer has to reach; its extension list is reusable, the git range is not.
- The tests commit is made in `stub_checks` (`1396`) or, in the old build, in `tests` (`1374`); the implementation commit is `implement`'s `r.commit(...)` (`1621`); the checks-loop fix
  commit is `1756`. `r.commit` (`wiring.py:849-915`) stages with `git add -A`, takes the lock and artifact filters, and on a rejected commit retries once as is, then
  hands the gate's output to a fix agent; the spec `commit-gate` says a hook that rewrote files is retried without an agent. No fixer pass runs before any of them.
- Protected paths are decided by `review_paths.is_protected(config, repo, path)` (`pipeline/review_paths.py:48`), already used by `nodes.py:1933`.

## What Changes

- **A profile method applies the fixers.** `ToolchainProfile.fix_command(files)` is declared in `profiles/base.py` beside `clean_command` as an optional capability (read tolerantly, as
  `supports_stubs` is: a profile without it gets no fixer pass) and implemented by both shipped profiles. Its argument is the unit's changed and untracked files in one project, relative to
  that project's directory. python-uv returns the pre-commit hooks over exactly those files; node-npm returns `npx oxfmt` (write) and `npx oxlint --fix` over those of them that are source files.
- **The runner runs it, not an agent.** A runner function (`run_fixers`, beside `run_stub_checks`) selects the files, groups them by project, runs each project's command in the project's directory
  with the exit status ignored, repeats up to two passes while a pass still changes something, never passes a file the policy protects, and writes one log line naming the files it changed.
  A failure to run is logged and never stops the build. It spends no model call and no usage.
- **It runs before every commit the pipeline makes in a build**: before the tests commit in the stub loop (ahead of the static check, so a formatter's edit is in the tree the check sees),
  before the implementation commit, before each `fix:` commit of the checks loop, and before the old build's tests commit and implementation commit. What is committed is already formatted.
- **A repo may replace the command**: `repos.<name>.tests.fix_command`, a list of arguments the file names are appended to, in `abk.yaml` (policy: it is the repo's own tooling and reads the same on every
  machine). Left out, the profile's command applies; `[]` turns the fixer pass off for the repo.
- **The two loops share one routine.** A shared check-and-fix helper holds what the two loops did twice: run the check, save a failure as feedback, count the round, stop when the rounds are spent,
  call the agent, apply the commit rule and stop when the fix step changed nothing. It takes the check as a callable returning `(ok, output)`, the fix prompt, the commit rule and the feedback source,
  and the counter to use. The stub loop passes the static checks (no test) and no commit rule; the checks loop passes the unit-test run and the `fix: <title> (checks, round N)` commit.
  `stub_checks`/`fix_stub_checks` and `checks`/`fix_checks` become thin callers of it. Their routes, state fields, messages and the feedback each saves are as they are.
- **The "changed nothing" stop is kept, now in one place.** It is not relaxed: with the fixers run before each commit, the case that made it wrong (a hook repairing a file during the check run, leaving the
  agent nothing to change) no longer reaches it. A fix round that changes nothing while the checks still fail stops the unit as today.
- **Docs and changelog**: `docs/architecture.md`, `docs/unit-graph.md` (the `stub_checks`, `fix_stub_checks`, `checks`, `fix_checks` rows), `docs/toolchain-profiles.md` (the new method), the `abk-config` skill
  (the new setting) and one `CHANGELOG.md` bullet.

## Impact

A unit whose files a formatter would change no longer fails or spends an agent call on it: the pipeline reformats before it commits, the check finds nothing to complain of, and the log shows `fixers changed N file(s)`.
A unit that was stopped by the third known stop of the stubbed build ("static checks failing and fix round N changed nothing" after a formatter run) is requeued with `--restart` as before and now passes the formatter. The
stubbed build's commit shapes are unchanged: still one `test:` then one `feat:` per group and no `fix:` commit in the stub loop. A repo whose profile lacks the method, or whose `fix_command` is `[]`, builds as it does today.
Review-round and rework commits (`fix: <title> (review round N)`, `fix: <title>`) are not given a fixer pass here.

## Not in this change

- **Relaxing the stop rule.** The "changed nothing" stop and `global_limits.max_check_rounds` stay; a later change can revisit them if another case shows up.
- **The commit shapes, the red check, the push gate, review rounds, the whole-repo unit-test run, flaky-test handling and affected-test selection**: none changes.
- **Repo-wide reformatting.** The fixers only reach the unit's own changed and untracked files.
- **Rework, review-round and adapt commits.** They keep the commit gate's retry (`commit-gate`) as their only formatter step.
- **A type fixer.** `tsc` and a Python type checker are not fixable and stay with the agent; node-npm's `fix_command` runs neither.
- **A fixer for third-party profiles.** A profile without `fix_command` behaves as today until its author adds it.
