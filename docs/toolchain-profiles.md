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
Two ship: `python-uv`, implemented, and `node-npm`, declared and not
implemented.

## The protocol

`profiles/base.py` defines `ToolchainProfile` as a `Protocol`:

| Member | Used by | What it answers |
|---|---|---|
| `name` | `abk.yaml`, the registry | the key a repo names |
| `detect_markers` | `abk init` | files whose presence in a repo root suggest this profile |
| `allowed_tools` | every build run | tool patterns to allow beyond the base list, in `--allowedTools` syntax; no effect under the `acp` runtime (docs/agent-runtimes.md) |
| `prompt_words` | the build prompts | `verify` ("what the checks pass means") and `stub` ("what a permitted stub looks like") |
| `no_tests_collected_exit` | tier 2, verify | the runner's exit status when nothing was selected — a pass, not a failure |
| `lint_command(base)` | tier 1 | lint scoped to the diff since `base` |
| `lint_command_all_files()` | tier 1 | lint of the whole repo — used only for a unit with no commits of its own, which has no diff to scope to |
| `test_commands(repo, changed, root_extras)` | tier 1 | the test runs a set of changed paths calls for |
| `test_commands_all(repo, root_extras)` | tier 1 | every test run the repo has, regardless of a diff — used only for a unit with no commits of its own |
| `tier2_commands(repo, marker)` | tier 2 without a dev stack | every member's live-stack tests |
| `acceptance_commands(checkout, paths, marker, exclude_marker, root_extras)` | post-merge verify | the live tests among a change's paths |
| `lint_command_all_files()` | `uv run pre-commit run --all-files` — tier 1 uses it only for a unit with no commits of its own |
| `clean_command()` | the push gate | lint and format at the tests commit, types skipped |
| `red_command(files)` | the push gate | run these test files at the tests commit |
| `interpret_red(output, exit_code)` | the push gate | was that run honestly red, and why not |
| `parse_test_summary(output)` | tier 2, verify | `(passed, failed, skipped, seconds)` |
| `is_test_path(path)` | verify, tier 1 | test paths deploy nothing |
| `stub_violations(path, content)` | the push gate | why a file is more than a declaration |
| `members(repo)` | tier 1, tier 2, verify | workspace members; empty for a single-package repo |
| `member_of(repo, path)` | verify | which member a path is in |
| `dependents(repo, member)` | verify | members that declare `member` as a dependency |

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
| `clean_command()` | `SKIP=pyrefly-check uv run pre-commit run --all-files` — type checking skipped: a test importing what does not exist yet is the expected state at the tests commit |
| `red_command(files)` | `uv run pytest <files> -p no:cacheprovider --tb=line -q` |
| `test_commands`, single-package repo | `uv run pytest -q` if `tests/` exists, else nothing |
| `test_commands`, workspace | per chosen member with a `tests/` dir: `uv run --package <name> --isolated pytest <member> -q`. Chosen: the members a changed path is under — or **every** member when a non-`.md` path outside all members changed (the root `pyproject.toml` is where a marker gets registered). Plus, when such an outside path or `tests/` changed and a repo-root `tests/` exists: `uv run --no-project --isolated --with pytest [--with <root_extras>...] pytest tests -q` |
| `test_commands_all(repo, root_extras)` | every testable member plus the root `tests/`, whatever changed — tier 1 uses it only for a unit with no commits of its own |
| `tier2_commands(marker)`, single-package | `uv run pytest -m <marker> -v` |
| `tier2_commands(marker)`, workspace | per member with `tests/`: `uv run --package <name> --isolated pytest <member> -m <marker> -v` |
| `acceptance_commands(...)` | the existing `.py` paths under `tests/integration/` among the changed paths, grouped by member: `uv run --package <name> --isolated pytest -m "<marker> and not <exclude_marker>" <files...>`; root files with the `--no-project --isolated --with ...` head instead |

And what it knows:

- `no_tests_collected_exit` is 5 (pytest's "no tests collected"); most
  members carry no tier-2 tests.
- `allowed_tools` is `Bash(uv run *) Bash(pre-commit *)`; the prompts say
  "linting, formatting and type checks (pre-commit)" and "a signature whose
  body is only `raise NotImplementedError`, or a model field".
- `is_test_path`: a `tests` directory anywhere above the file, or a file named
  `test_*.py`, `*_test.py` or `conftest.py`.
- `stub_violations`: Python files are parsed with `ast`; every function body
  must be only `pass`, `raise NotImplementedError`, or a constant (after a
  docstring). Unparseable is a violation. Other languages get no opinion.
- `interpret_red` reads pytest's summary: passing tests, nothing collected,
  `SyntaxError`/`IndentationError`, a missing fixture or a broken conftest
  disqualify the run; an assertion, `NotImplementedError`, `ModuleNotFoundError`,
  `ImportError` or `AttributeError` is red for the right reason.
- `parse_test_summary` counts `N passed/failed/skipped/error` and `in Ns`.
- `members` reads `[tool.uv.workspace].members` from the root `pyproject.toml`;
  `dependents` reads each other member's `[project].dependencies` and
  `optional-dependencies`, normalising names (`-`, `_`, `.` and case).

## `node-npm`

Declared so that `abk init` detects JavaScript/TypeScript repos and writes
their specs — research and proposal are language-agnostic — and so the
planner can place units in them. It is **not implemented**: every command
method raises `NotImplementedError`, and `abk tick` catches that when it
tries to build a unit in such a repo, logs it, and puts the unit in `held`
(nothing a retry changes; a person builds it by hand or changes the plan).

What exists: `detect_markers` (`package-lock.json`, `package.json`),
`allowed_tools` (`Bash(npm *) Bash(npx *)`), the prompt words ("linting and
type checks (oxlint, tsc --noEmit)", a stub body of
`throw new Error("not implemented")`), `no_tests_collected_exit` 0,
`is_test_path` (a `__tests__` directory, or `.test.ts`/`.spec.ts`/`.test.js`),
and `stub_violations` returning nothing.

What it would need, method by method: `npm test --workspace <member>` with a
summary parser for the chosen runner; `npx oxlint` and `npx tsc --noEmit` as
the lint and clean commands; `members`/`member_of`/`dependents` from
`package.json` workspaces; a red-output interpreter for the runner; and a
stub checker for the `throw` body.

## Adding a profile

There is no plugin discovery: the registry is filled in-process by
`profiles._load_builtin`, which imports the built-in modules and calls
`profiles.register(PROFILE)` on each. To add one:

1. Add `profiles/<name>.py` with a class satisfying `ToolchainProfile` (a
   plain class; the protocol is structural) and a module-level `PROFILE`
   instance. Reuse `pipeline/commit_order.stub_violations`,
   `pipeline/red_check.interpret_pytest` and `pipeline/tier2.parse_pytest_summary`
   where the toolchain's output is pytest-shaped; otherwise write the
   equivalents beside the profile.
2. Register it in `_load_builtin` (or call `profiles.register` before the
   first `get` in an embedding program).
3. Teach `init/detect.py` the markers that select it, if detection should.
4. Tests go in `tests/profiles/`, with the fixture repos as the only
   installation.

Every fact about a toolchain — commands, exit codes, what a test path is,
what a stub may contain, prompt wording — belongs in the profile, not in the
pipeline modules that call it.
