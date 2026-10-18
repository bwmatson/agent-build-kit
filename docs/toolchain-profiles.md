# Toolchain profiles

The pipeline lints, runs tests, reads their results, tells test files from
implementation and checks that a stub is only a stub. Every one of those is
language-specific, so each lives in a **profile** (`profiles/`) and the rest
of the pipeline asks the profile. A repo names its profile in `abk.yaml`:

```yaml
repos:
  app:
    profile: python-uv     # the default
```

`profiles.get(name)` returns it; an unknown name raises with the known list.
Two ship: `python-uv` and `node-npm`, both implemented.

## The protocol

`profiles/base.py` defines `ToolchainProfile` as a `Protocol`:

| Member | Used by | What it answers |
|---|---|---|
| `name` | `abk.yaml`, the registry | the key a repo names |
| `detect_markers` | `abk init` | files whose presence in a repo root suggest this profile |
| `allowed_tools` | every build run | tool patterns to allow beyond the base list, in `--allowedTools` syntax; no effect under the `acp` runtime (docs/agent-runtimes.md) |
| `prompt_words` | the build prompts | `verify` ("what the checks pass means") and `stub` ("what a permitted stub looks like") |
| `no_tests_collected_exit` | e2e-test, verify | the runner's exit status when nothing was selected — a pass, not a failure |
| `lint_command(base)` | unit-test | lint scoped to the diff since `base` |
| `lint_command_all_files()` | unit-test | lint of the whole repo — used only for a unit with no commits of its own, which has no diff to scope to |
| `extra_checks(repo)` | unit-test | commands about the checkout as a whole (the python profile's changelog check). Unit-test runs the repo profile's once, in the checkout root, whatever the unit touched |
| `project_checks(repo)` | unit-test | optional: commands about one project (the node profile's type check, which cannot be scoped to files). Unit-test runs them in the directory of each project the unit touched, under that project's own profile, and in the checkout root for a repo with no projects; a profile without the method counts as returning `[]`. Declared as `profiles.base.ProjectChecks` |
| `failure_kind(output)` | unit-test failures, telemetry | `lint`, `types` or `test`, read from the failed command's `$` header. The profile of the project the failed command ran in reads it (unit-test writes the directory under the header, `check_failures.failed_in`); the repo's profile reads a failure that names no project directory |
| `test_commands(repo, changed, root_extras)` | unit-test | the test runs a set of changed paths calls for |
| `test_commands_all(repo, root_extras)` | unit-test | every test run the repo has, regardless of a diff — used only for a unit with no commits of its own |
| `affected_test_commands(repo, changed_files, failed_ids, *, seed, root_extras)` | unit-test, fix rounds and a scoped moved base | optional: the commands that run the tests the change affects, `[]` for none, or `None` when the profile cannot say — which a profile without the method does too. `failed_ids` come from the profile's `failed_tests`; `seed` is a path it may keep selection data in (a file under the project's git-excluded `.abk/` folder); `root_extras` are the repo's `tests.root_extras`, as for `test_commands`. A fix round's check uses it, and the full suite always confirms (see `checks.affected` in `configuration.md`); a scoped moved base (see `global_limits.restack_check`) asks it once with the unit's files and the files the move brought in and no failed ids, and no full run confirms that. The Python profile answers `None` there, and so the full suite runs, when a changed file is not a document, a `.py` source file or a `test_*` module (a lock or configuration file, a `conftest.py`, a shared test helper) |
| `seeding_command(command, seed, *, select=False)`, `is_seeded(command)` | unit-test, full runs and fix rounds | optional: `command`, a test run, as one that keeps its selection data at `seed`, running every test, or only the affected ones with `select`. A full run in a repo with `checks.affected` on uses it, so the data a later selection reads is recorded; a profile without it records nothing. A seeded command that fails with no test result (the plugin could not be installed) is run again without it, and a seeded selection that does so falls back to the full suite, with one log line. `is_seeded` tells which commands those are. The Python profile adds the coverage plugin (`pytest-testmon`) to the run's isolated environment and keeps its data file at `seed`: with that data `affected_test_commands` selects by the source each test executed, and without it (a rebuilt worktree) it runs the failed identifiers alone, or returns `None` when there are none. Each selected run writes an `affected` line to the usage ledger: unit, node, round, tests selected and in all, estimated seconds saved (the last full run's test time less the selected run's, never negative, absent with no full run to compare with) and `agreed`, `disagreed` or `not_run`; a scoped moved base's passing run writes one too, with `moved`, which no full run confirms |
| `created_files(repo)` | worktree check, commit step, restack | optional: the paths or patterns, relative to `repo` and `/` separated, of the files the profile's own commands create or rewrite in a worktree (not what a build produces, which is `environment.artifacts`). `[]` for none, which a profile without the method also counts as. Absolute paths, paths with `..` and `.git` are ignored. The pipeline owns them, with or without an `environment` section: an untracked one is never a leftover and never committed; a tracked one follows the lock rule where the environment declares dependency inputs, and is ordinary work otherwise. A repository's `projects` own each profile's paths under the project's path |
| `agent_commands` | the build prompts | optional, and each command it names must match the build allow-list; declared as `profiles.base.AgentCommands`: a tuple of `config.AgentCommand` (purpose `test`, `lint`, `format` or `check`; the command as an argument list; scope `whole`, `file` or `node-id`, with `{path}` in the command exactly when the scope is not `whole`) naming what a build agent may run. A profile without it names none. Each command must match the build allow-list (`wiring.allowed_tools` for the repo, its forge and its projects, judged by `tool_patterns.allows`, which refuses a line that chains another command), or the agent's run refuses it. `repos.<name>.agent_commands` replaces them (see `configuration.md`) and is refused at load when one does not match; for a profile's own list `abk doctor` reports a FAIL |
| `e2e_commands(repo, marker)` | e2e-test without a dev stack | every member's live-stack tests |
| `acceptance_commands(checkout, paths, marker, exclude_marker, root_extras)` | post-merge verify | the live tests among a change's paths |
| `clean_command()` | the push gate | lint and format at the tests commit, types skipped |
| `red_command(files)` | the push gate | run these test files at the tests commit |
| `interpret_red(output, exit_code)` | the push gate | was that run honestly red, and why not |
| `parse_test_summary(output)` | e2e-test, verify | `(passed, failed, skipped, seconds)` |
| `parse_test_failures(output)` | e2e-test | `TestFailure(test, line)` for each failed or errored test, in printed order; `[]` when the output has none. The python profile asks pytest for them with `-rfE --tb=short` |
| `is_test_path(path)` | verify, unit-test | test paths deploy nothing |
| `stub_violations(path, content)` | the push gate | why a file is more than a declaration |
| `members(repo)` | unit-test, e2e-test, verify | workspace members; empty for a single-package repo |
| `member_of(repo, path)` | verify | which member a path is in |
| `dependents(repo, member)` | verify | members that declare `member` as a dependency |
| `detect_environment(root, framework)` (optional) | `abk init` | the proposed `environment` section for a checkout, or `None` when the profile cannot say; a profile without it counts as returning `None`; declared as `profiles.base.EnvironmentDrafting`, which the walk selects on. A draft can be a `config.DraftedEnvironment`, whose `note` init writes as a comment above the section. `profiles.registered(profile)` registers one for a `with` block |

`profiles.base.is_doc_path` is not a profile method: `.md`/`.rst`/`.txt`,
anything under `docs/`, and `LICENSE*` never deploy, whatever the profile.

## `python-uv`

A Python repo managed by `uv`, tested with pytest, gated by pre-commit
(ruff, a type checker). A `uv` workspace is tested **one member at a time in
its own environment**, the way such a repo's CI runs: members tend to own a
top-level `src` package, so one shared environment makes one member's tests
import another's. `--package <name> --isolated` reproduces the one-member
environment. The package name comes from the member's `pyproject.toml`
(`[project].name`), falling back to its directory name; the trailing path
argument is the directory.

What it runs, exactly:

| Method | Command |
|---|---|
| `lint_command(base)` | `uv run pre-commit run --from-ref <base> --to-ref HEAD` — scoped to the diff, so a unit is not failed for problems in files it never touched |
| `lint_command_all_files()` | `uv run pre-commit run --all-files` — unit-test uses it only for a unit with no commits of its own |
| `clean_command()` | `SKIP=pyrefly-check uv run pre-commit run --all-files` — type checking skipped: a test importing what does not exist yet is the expected state at the tests commit |
| `red_command(files)` | `uv run pytest <files> -p no:cacheprovider --tb=line -q` |
| `test_commands`, single-package repo | `uv run pytest -q` if `tests/` exists, else nothing. A repo that declares `pytest-xdist` (project dependencies, extras, dependency groups) gets two commands instead, mirroring `poe test`: `uv run pytest -n auto --maxprocesses=8 -m 'not serial' -q`, then `uv run pytest -m serial -q`, whose exit 5 (nothing marked `serial`) counts as a pass. The repo's own `addopts` `-m` expression is kept: `(<it>) and not serial`. A repo without xdist keeps the plain command, since `-n` would be rejected there |
| `test_commands`, workspace | per chosen member with a `tests/` dir: `uv run --package <name> --isolated pytest <member> -q` (the two xdist passes above instead, when the member's own `pyproject.toml` declares `pytest-xdist`). Chosen: the members a changed path is under — or **every** member when a non-`.md` path outside all members changed (the root `pyproject.toml` is where a marker gets registered). Plus, when such an outside path or `tests/` changed and a repo-root `tests/` exists: `uv run --no-project --isolated --with pytest [--with <root_extras>...] pytest tests -q` (the two xdist passes instead, when `root_extras` names `pytest-xdist`) |
| `test_commands_all(repo, root_extras)` | every testable member plus the root `tests/`, whatever changed — unit-test uses it only for a unit with no commits of its own |
| `e2e_commands(marker)`, single-package | `uv run pytest -m <marker> -v` |
| `e2e_commands(marker)`, workspace | per member with `tests/`: `uv run --directory <member> --package <name> --isolated pytest -m <marker> -v` (no path: the member's own pytest configuration, `testpaths` included, decides what is collected) |
| `acceptance_commands(...)` | the existing `.py` paths under `tests/integration/` among the changed paths, grouped by member: `uv run --package <name> --isolated pytest -m "<marker> and not <exclude_marker>" <files...>`; root files with the `--no-project --isolated --with ...` head instead |

And what it knows:

- `no_tests_collected_exit` is 5 (pytest's "no tests collected"); most
  members carry no e2e-test tests.
- `allowed_tools` is `Bash(uv run *) Bash(uv lock*) Bash(uv sync*) Bash(uv add *)
  Bash(uv remove *) Bash(pre-commit *)`. A builder that changes dependencies
  needs `uv lock`, `uv sync`, `uv add` and `uv remove`, and a headless run
  denies any command not listed; all four act on the project in the current
  directory (the unit's worktree). The policy hook does not inspect uv's
  `--project` or `--directory` flags, which `uv run` already allowed. Commands
  that install outside the project (`uv publish`, `uv tool install`,
  `uv python install`, `uv pip install`) are not listed. Of the `uv run`
  commands, the build prompts name the ones in `agent_commands`: `uv run pytest -q`
  (and with a path), `uv run pre-commit run --all-files` (and `--files <path>`),
  so an agent does not pick a spelling the list refuses. The prompts say
  "linting, formatting and type checks (pre-commit)" and "a signature whose
  body is only `raise NotImplementedError`, or a model field".
- `agent_commands` are the four commands above, as test and check at whole and file
  scope; the node profile gives `npx vitest run` (and with a path), `npx oxlint .`,
  `npx oxfmt --check .` and `npx tsc --noEmit`. A workspace member that needs
  `--package <name> --isolated` is what the repo's own `agent_commands` is for.
- `is_test_path`: a `tests` directory anywhere above the file, or a file named
  `test_*.py`, `*_test.py` or `conftest.py`.
- `stub_violations`: Python files are parsed with `ast`; every function body
  must be only `pass`, `raise NotImplementedError`, or a constant (after a
  docstring). Unparseable is a violation. Other languages get no opinion.
- `interpret_red` reads pytest's JUnit report (`red_command` writes it with
  `--junitxml` to a temp file and prints it after the console output; only
  the `<testsuites>` span is read, so stderr after it is ignored), judging each failing
  test by its exception: a collection error, a missing fixture, a broken
  conftest (a fixture that raises `NotImplementedError` at setup is red, as
  it is calling the stub), `SyntaxError`/`IndentationError` or a passing test disqualify the
  run; an assertion, `NotImplementedError`, `ModuleNotFoundError`,
  `ImportError` or `AttributeError` in a test body is red for the right reason.
  When no report can be read, the console summary is matched instead and a
  warning says the fallback ran. Recorded reports live under
  `tests/fixtures/external/pytest/`; re-record them with
  `uv run python tests/fixtures/external/record_pytest.py`.
- `parse_test_summary` counts `N passed/failed/skipped/error` and `in Ns`.
- `members` reads `[tool.uv.workspace].members` from the root `pyproject.toml`;
  `dependents` reads each other member's `[project].dependencies` and
  `optional-dependencies`, normalising names (`-`, `_`, `.` and case).

## `node-npm`

A JavaScript/TypeScript repo managed by npm, linted with oxlint and oxfmt, type-checked
with `tsc` and tested with Vitest. An npm workspace is tested **one member at a time in
its own directory**. Members come from the root manifest's `workspaces` field (the array
form, and the object form's `packages`); glob patterns are expanded and a directory
without a `package.json` is not a member. Negated patterns and nested workspaces are not
supported. pnpm and yarn workspaces are not read.

What it runs, exactly:

| Method | Command |
|---|---|
| `lint_command(base)` | `npx oxlint` and `npx oxfmt --check` over the `ts`, `tsx`, `js`, `jsx` and `mts` files that differ from `base`, relative to the project; fails when `base` does not resolve |
| `lint_command_all_files()` | `npx oxlint . && npx oxfmt --check .` |
| `clean_command()` | the same, with no `tsc`: a test importing what does not exist yet is the expected state at the tests commit |
| `project_checks` | `npx tsc --noEmit`, the type check as its own check, over the whole project in its directory |
| `red_command(files)` | `npx vitest run <files> --reporter=junit`, the report printed after a marker, after a line for each given file |
| `test_commands`, single package | `npx vitest run --passWithNoTests --reporter=junit`, the report in a temporary file printed after the report marker |
| `test_commands`, workspace | one such run in the directory of each member a changed path is under, or in **every** member when a non-documentation path outside all members changed (the root manifest, shared configuration); a test file outside every member is run from the root, filtered to it |
| `test_commands_all(repo, root_extras)` | every member, whatever changed |
| `e2e_commands(marker)` | per member (or the project): the same run filtered to files named `<name>.<marker>.test.<ext>` |
| `acceptance_commands(...)` | the changed files that exist, carry the marker and not the dev-stack marker's, one run per member with those files as filters |

**The marker is a file-name segment.** Vitest has no tag filter that serves selection,
exclusion and path-based acceptance together, so a node project's e2e tests are the
files named `<name>.<marker>.test.ts[x]`, with `<marker>` the repo's `tests.e2e_marker`
(`local_stack` by default). The e2e-test run takes the files carrying it; post-merge verify leaves out
the files carrying `tests.dev_stack_marker`; acceptance runs the changed marked files.
Unit-test is the project's or member's whole Vitest run and does not leave marked files
out, so a marked test must skip itself when the stack is absent. Excluding marked files in the
Vitest configuration hides them from the e2e-test run too, which selects by the same
file-name substring after the configuration's `exclude` applies.

And what it knows:

- `failure_kind` reads the failed command in the `$` header: the type checker is `types`,
  the test runner is `test`, the linter and format check are `lint`.
- `parse_test_summary`, `parse_test_failures` and `parse_test_durations` read the JUnit
  report, one failure per failing `testcase`, named `file > test`. Recorded reports live
  under `tests/fixtures/external/vitest/`; re-record them with
  `uv run python tests/fixtures/external/record_vitest.py`.
- `detect_markers` (`package-lock.json`, `package.json`), `allowed_tools`
  (`Bash(npm *) Bash(npx *)`), the prompt words ("linting and type checks (oxlint,
  tsc --noEmit)", a stub body of `throw new Error("not implemented")`),
  `no_tests_collected_exit` 0.
- `is_test_path`: a `__tests__` directory, or `.test`/`.spec` before `ts`, `tsx`, `js`,
  `jsx` or `mts`.
- `interpret_red` judges only the suites named after the given files, which the red
  command printed before the report: a failure of type `AssertionError` or an error whose
  message is `not implemented` is red; a file that failed to load (its testcase is named as
  the file), any passing test, a given file with no failing test and any other failure are
  each rejected with a reason.
- `stub_violations` (parsed with tree-sitter): every function, method or arrow body, at any
  depth, must be only `throw new Error("not implemented")`, comments aside; a function
  without a body is accepted; an unparseable file is a violation; test files and non-source
  extensions are not checked.
- `created_files`: `**/*.tsbuildinfo`, `node_modules/.vite`, `node_modules/.vitest` and
  `.vite`.
- `members` reads the `workspaces` field as above; `member_of` names the deepest member
  holding a path; `dependents` reads each other member's `dependencies`,
  `devDependencies` and `peerDependencies` for the member's package name.
- It drafts the environment for `abk init` from a `package.json`
  (`profiles/node_environment.py`): the manager is the manifest's `packageManager` field,
  else the lock file present (`package-lock.json` npm, `pnpm-lock.yaml` pnpm, `yarn.lock`
  yarn), else npm. `sync` is the plain install (never a frozen one, which fails for the unit
  that changed a dependency), `check` a depth-0 listing, the manifest and lock files are
  inputs, a `workspaces` field adds `<workspace>/package.json` patterns, and `node_modules`
  is an artifact.

A profile method that raises `ProfileUnsupported` still makes `abk tick` log it and put the
unit in `held`; the node profile raises none.

## Adding a profile

There is no plugin discovery: the registry is filled in-process by
`profiles._load_builtin`, which imports the built-in modules and calls
`profiles.register(PROFILE)` on each. To add one:

1. Add `profiles/<name>.py` with a class satisfying `ToolchainProfile` (a
   plain class; the protocol is structural) and a module-level `PROFILE`
   instance. Reuse `pipeline/commit_order.stub_violations`,
   `pipeline/red_check.interpret_pytest` and `pipeline/e2e.parse_pytest_summary`
   where the toolchain's output is pytest-shaped; otherwise write the
   equivalents beside the profile.
2. Register it in `_load_builtin` (or call `profiles.register` before the
   first `get` in an embedding program).
3. Teach `init/detect.py` the markers that select it, if detection should, and give
   the profile `detect_environment` if `abk init` should draft its environment: init
   asks the profile detection chose first, then the rest in registration order.
4. Tests go in `tests/profiles/`, with the fixture repos as the only
   installation.

Every fact about a toolchain — commands, exit codes, what a test path is,
what a stub may contain, prompt wording — belongs in the profile, not in the
pipeline modules that call it.

## Infrastructure profiles

A second profile kind, built the same way, covers what a repo runs on rather
than what it is written in, so container tooling is not tied to the language.
A repo names it in `abk.yaml` (`infra:`, default `none`):

```yaml
repos:
  app:
    profile: python-uv
    infra: docker
```

`infra/base.py` defines `InfraProfile` as a `Protocol` (`name`,
`detect_markers`, `stack_versions_command`); `infra.get(name)` and
`infra.names()` mirror `profiles`. An unknown name fails when `abk.yaml`
loads, naming the registered ones. Two ship:

| Profile | Markers (`abk init`) | `stack_versions_command` |
|---|---|---|
| `docker` | a compose file (`compose.yaml`, `docker-compose.yml`, ...) or `Dockerfile` | `docker ps --format "{{.Names}}\t{{.Image}}"` |
| `none` | none | none: nothing is recorded or run |

E2e-test records the command's output beside its result, resolved by
`config.stack_versions_for`: `verify.stack_versions_command` when a list
(installation-wide override), else the repo's infra profile's command; an
explicit `null` records nothing. To add a profile: `infra/<name>.py` with a
module-level `PROFILE`, registered in `infra._load_builtin`, tests in
`tests/infra/`.
