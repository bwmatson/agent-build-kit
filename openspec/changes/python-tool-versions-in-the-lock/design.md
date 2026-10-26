# Design

## The hooks

```yaml
- repo: local
  hooks:
    - id: ruff-format
      name: ruff format
      entry: uv run --frozen ruff format
      language: system
      types: [python]
    - id: ruff-check
      name: ruff check
      entry: uv run --frozen ruff check --fix
      language: system
      types: [python]
    - id: pyrefly-check
      name: pyrefly check
      entry: uv run --frozen pyrefly check
      language: system
      pass_filenames: false
      files: ^(src|tests)/
```

`--frozen` runs against the lock as it is and never resolves or edits it, so a
hook cannot change a dependency by being run. The type checker reads
`[tool.pyrefly]` and the project's environment itself; no interpreter path is
needed.

## Where each version lives

| Tool | Owner |
|---|---|
| ruff, pyrefly | `uv.lock`, via the dev dependency group |
| pre-commit, poe, pytest | the same lock |
| whitespace, end-of-file, merge-conflict, large-file, toml hooks | `.pre-commit-<redacted>` `rev` |
| yamllint | `.pre-commit-<redacted>` `rev` |

The editor, a bare `uv run ruff`, unit-test and CI run one binary for the Python
tools, because all of them use the project's environment.

## The environment must exist

A local hook fails if the project is not synced. CI and the pipeline already run
`uv sync` first. For a person, the failure is a tool-not-found error from
`uv run`, which would be an unhelpful message at commit time; the hook entry
therefore goes through `uv run --frozen`, which creates the environment from
the lock when it is missing, so a fresh clone's first commit syncs it.

## The lock is part of the gate

`--frozen` makes a missing `uv.lock` an error, not a reason to resolve. A
checkout, a worktree or a scratch repo that runs the gate therefore needs the
lock beside `pyproject.toml` and the hook configuration. The habitat test's set
of copied gate files includes it; it is the test that exists to prove the gate
works in a fresh worktree.

## Updates

`pre-commit autoupdate` no longer touches ruff or pyrefly. They are updated with
`uv lock --upgrade-package`, which the dependency-update check already knows
how to do; `uv lock --check` in CI catches a pin that was edited without
relocking.

## Which repos this suits

A repo that syncs a Python environment before committing, which is every repo
the recommendations are written for. A repo without a Python environment keeps
the hook-owned arrangement; `abk init` offers this one only for a `python-uv`
profile.

## `abk doctor`

Two checks, both warnings: a tool pinned in the dependency group and also run
from a hook repository with its own `rev`; and a `language: system` hook whose
tool is absent from the dependency group, so the hook can only fail.

## Out of scope

Checking that a type checker examined every Python file the repo has. That is a
separate gate concern and gets its own change.
