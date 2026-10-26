# Proposal

## Why

The formatter, linter and type checker are pinned twice in a Python repo: the
`rev` of their hooks in `.pre-commit-<redacted>`, and the dev dependency group
in `pyproject.toml`. The config comment says why (the hook version is what CI
enforces, the dependency is for the editor) and warns that "the editor stops
agreeing with CI" if one is bumped without the other. Two copies of a version
are two things to keep equal, and nothing checks that they are.

The hooks also run in an isolated environment that holds the tool and nothing
else. The type checker therefore needs `--python-interpreter-path
.venv/bin/python` to see the project's packages, and it is run apart from the
project, in a version and path context the project does not control. A mismatch
between that run and the project's own already cost a unit's checks: one hook
version skipped a repo's tests where the project's copy did not.

## What Changes

- **The project's lock owns the Python tools' versions.** `ruff` and `pyrefly`
  stay in the dev dependency group, and the lock pins them exactly. Their hooks
  stop carrying a `rev` of their own.
- **Their hooks run the project's copy.** `repo: local` hooks with
  `language: system` call `uv run ruff …` and `uv run pyrefly check`, in the
  project's environment. The interpreter-path argument and the isolated hook
  environment go.
- **The other hooks stay as they are.** Whitespace, end-of-file, merge-conflict
  and large-file checks, toml and yaml linting are not project dependencies and
  keep their `rev`. The pre-commit file owns those; the lock owns the Python
  tools. No tool has two owners.
- **Unit-test, CI and a person run the same thing.** `pre-commit run` is still the
  entry point, now calling the locked tools, after `uv sync`.
- **The recommendations say so.** The Python recommendations seed describes the
  arrangement, so a repo `abk init` sets up does not grow a second pin.
- **`abk doctor` warns** when a tool the repo pins in its dependency group also
  appears as a pinned hook, and when a local hook is run without a synced
  environment.
