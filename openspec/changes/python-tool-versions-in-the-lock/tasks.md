# Tasks

Acceptance: none — tooling configuration and a doctor warning; tier-1 tests over
the doctor checks and the packaged seed prove it.

## 1. [agent-build-kit] [unit-test] The lock owns the Python tool versions

Done when this repo's formatter, linter and type checker run from the locked
project environment through local hooks, their hook `rev`s are gone, and
`abk doctor` and the seed enforce the arrangement for other repos.

- [x] 1.1 Test: `abk doctor` on a repo whose dependency group pins ruff or
      pyrefly and whose hooks also run it from a repository with a `rev` warns
      once per tool naming both files; a tool pinned in one place only is
      silent.
- [x] 1.2 Test: `abk doctor` warns on a `language: system` hook running a tool
      that is not in the dependency group, and is silent when it is.
- [x] 1.3 Test: the Python recommendations seed describes the locked tools and
      local hooks, gives its verify steps as `pre-commit run` commands, and
      names no hook `rev` for ruff or pyrefly.
- [x] 1.4 Add the two doctor checks and update the recommendations seed.
- [x] 1.5 Replace this repo's ruff and pyrefly hooks with local hooks that run
      `uv run --frozen`, drop their `rev`s and the interpreter-path argument,
      keep the other hooks as they are, and rewrite the comment that explained
      the double pin.
- [x] 1.6 Check that unit-test (`pre-commit run --from-ref`), CI and a fresh
      worktree each run the locked ruff and pyrefly, and that the type checker
      checks the `tests` directory in a worktree under the pipeline's state
      directory.
- [x] 1.7 Replace direct tool invocations in `AGENTS.md` and `docs/` that
      disagree with the arrangement, and add a changelog entry.
- [x] 1.8 Test: the habitat test (`tests/integration/test_worktree_gate.py`)
      commits a trivially correct file in a scratch worktree through the local
      hooks and passes: the gate files it copies include `uv.lock`, since
      `uv run --frozen` fails without a lock.
- [x] 1.9 Add `uv.lock` to that test's gate files.
