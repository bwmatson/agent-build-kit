# Python: tooling recommendations (seed)

> **This is a seed, not a verdict.** It is the framework's starting position
> for a Python repo. `abk init`'s research step hands it to a model with web
> access, which validates every item against current practice as of the day
> it runs, keeps, amends or drops it with sources, and writes the result to
> the planning repo's `docs/recommendations/python.md`. That file is what the
> proposals are written from; this one is only where it starts.

Each item states the rule, the tool and its version floor, why, and how to
check that a repo follows it.

## Formatting

- **Rule:** one formatter, run by pre-commit and CI, no per-file exceptions.
  **Tool:** `ruff format` (ruff ≥ 0.16), line length 100.
  **Why:** a single formatter removes every formatting comment from review;
  100 columns fits two panes and leaves room for descriptive names.
  **Verify:** `uv run ruff format --check .` exits 0; `[tool.ruff]` has
  `line-length = 100`.

## Linting

- **Rule:** lint with ruff, selecting `E, F, I, UP, B`, with `--fix` only in
  the pre-commit hook, never in a bare CLI run.
  **Tool:** `ruff check` (ruff ≥ 0.16).
  **Why:** `E`/`F` catch errors, `I` keeps imports sorted so diffs stay small,
  `UP` keeps syntax current with `requires-python`, `B` flags the bug-shaped
  patterns (mutable defaults, unused loop variables).
  **Verify:** `[tool.ruff.lint] select = ["E", "F", "I", "UP", "B"]`;
  `uv run ruff check .` exits 0.

## Types

- **Rule:** a strict type checker runs on every workspace member, in CI and
  pre-commit, with zero tolerance.
  **Tool:** pyrefly ≥ 1.2, configured in `[tool.pyrefly]` with a
  `search-path` entry per member (`src`, or each member's `src`).
  **Why:** a checker that sees each member's source root resolves imports
  the way the interpreter does; without the search path it silently degrades
  to a lenient preset and reports nothing.
  **Verify:** `uv run pyrefly check` exits 0; `[tool.pyrefly]` lists
  `python-version` and `search-path`.

- **Rule:** the pre-commit hook for the type checker points at the project's
  own interpreter.
  **Tool:** pyrefly's pre-commit hook with `--python-interpreter-path
  .venv/bin/python`.
  **Why:** pre-commit runs hooks from an isolated environment that holds the
  checker and nothing else, so third-party types resolve to nothing.
  **Verify:** `.pre-commit-config.yaml`'s pyrefly hook carries the argument
  and CI runs `uv sync` before pre-commit.

## Test layout & tiers

- **Rule:** pytest with three markers — `integration` (needs a real
  datastore), `local_stack` (needs the real local stack) and `dev_stack`
  (only the disposable dev stack can run it) — all excluded by default.
  **Tool:** pytest ≥ 8, `[tool.pytest.ini_options]` with `markers` and
  `addopts = "-m 'not integration and not local_stack and not dev_stack'"`.
  **Why:** a bare `pytest` must pass anywhere, including CI with no services;
  the marked tiers are run on purpose with `pytest -m <marker>`.
  **Verify:** the three markers are declared; `pytest` on a fresh checkout
  with no services passes.

- **Rule:** tests mirror the source layout: a test sits in the folder
  matching the module's folder under the package root. Integration tests
  (anything marked) go under `tests/integration/`, mirrored the same way. A
  file that mixes marked and unmarked tests is split.
  **Tool:** convention, checked in review.
  **Why:** an agent looking for the tests of `src/x/y.py` finds them in
  `tests/x/` without a search, and the tier split is visible from the path.
  **Verify:** every `tests/**/test_*.py` has a source folder it mirrors; no
  marker appears in a file outside `tests/integration/`.

- **Rule:** no test calls a live website; recording a fixture from one and
  replaying it is fine, and the test names the source of the recording.
  **Tool:** convention; recorded fixtures under `tests/fixtures/`.
  **Why:** a live call is flaky, slow and unreviewable; a recording is a
  fact about a moment that review can inspect.
  **Verify:** the suite passes with the network unavailable.

## Packaging & workspaces

- **Rule:** one `uv` workspace per repo; members are tested one at a time in
  an isolated environment (`uv run --package <member> --isolated pytest`).
  **Tool:** uv ≥ 0.5, `[tool.uv.workspace] members`.
  **Why:** members tend to own a top-level `src` package; one environment
  holding all of them lets one member's tests import another's.
  **Verify:** `uv lock --check` exits 0; a per-member test run passes in
  isolation.

## Configuration & types conventions

- **Rule:** environment configuration goes through `pydantic-settings`, one
  settings class per service, never `os.environ` in new code.
  **Tool:** pydantic-settings ≥ 2.
  **Why:** one place to read what a service needs, validated at startup.
  **Verify:** `grep -rn "os.environ" src/` finds only the settings module.

- **Rule:** types are pydantic models, frozen where immutable, with
  `extra="forbid"` at every boundary; dataclasses are not used to declare a
  type.
  **Tool:** pydantic ≥ 2.
  **Why:** one way to declare a type means one set of validation,
  serialization and copy semantics.
  **Verify:** no `@dataclass` on a type that is parsed or serialized.

- **Rule:** tool configuration lives in `pyproject.toml` under `[tool.*]` for
  every tool that reads it (ruff, pytest, pyrefly, uv, poe); a tool that
  cannot keeps its own file at the repo root, named in the pre-commit hook
  that runs it.
  **Tool:** convention.
  **Why:** editors, a bare CLI run and the pre-commit gate read the same
  settings.
  **Verify:** no `ruff.toml`, `pytest.ini` or `setup.cfg` in the repo.

## Pre-commit

- **Rule:** pre-commit runs the basic hygiene hooks, yamllint in strict mode,
  ruff, ruff-format and the type checker; CI runs the same config.
  **Tool:** pre-commit ≥ 4; pre-commit-hooks ≥ 6.0 (`trailing-whitespace`,
  `end-of-file-fixer`, `check-toml`, `check-merge-conflict`,
  `check-added-large-files`); yamllint ≥ 1.38 with `--strict` and a
  `.yamllint` at the repo root.
  **Why:** one gate the developer and CI both run; yamllint reads only its own
  file, so it is the one tool with a config outside `pyproject.toml`.
  **Verify:** `uv run pre-commit run --all-files` is clean; CI's pre-commit
  job runs it with `--show-diff-on-failure`.

## CI

- **Rule:** tier 1 runs on GitHub Actions on every pull request and on
  pushes to the default branch: one pre-commit job, and one test job per
  workspace member; `uv lock --check` guards the lockfile.
  **Tool:** GitHub Actions with `astral-sh/setup-uv` and `actions/setup-python`.
  **Why:** a per-member job reproduces the isolated environment the tests
  are written for, and a stale lockfile fails here rather than on a deploy.
  **Verify:** `.github/workflows/ci.yml` has the jobs; a PR with a
  formatting error goes red.
