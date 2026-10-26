# Tasks

Acceptance: none — test tooling; the suite passing in parallel, repeatedly,
proves it.

## 1. [agent-build-kit] [tier1] Run the suite in parallel

Done when `poe test` runs the whole suite across workers in a fraction of the
serial time, passes repeatedly, and a single file still runs in one process.

- [x] 1.1 Test: a repository-level check that `pyproject.toml` declares
      `pytest-xdist` among the dev dependencies, that `poe test` passes `-n`,
      and that `addopts` does not (so a single file stays single-process).
- [x] 1.2 Test: the `serial` marker is declared in `pyproject.toml`, excluded
      from the parallel pass by `poe test`, and run by its own serial pass.
- [x] 1.3 Add `pytest-xdist` to the dev dependencies, `-n auto` with a
      `--maxprocesses` cap to `poe test`, and the `serial` marker.
- [x] 1.4 Run the suite in parallel ten times, and fix every test that fails
      only in parallel with its own `tmp_path`, port or environment; mark as
      `serial` what truly cannot share a process.
- [x] 1.5 Make the process-exit tests that fail under load tolerant of it, or
      mark them `serial`, whichever the cause shows.
- [x] 1.6 Make the python profile's test command and CI use the same command.
- [x] 1.7 Update the `Running` section of `AGENTS.md`, `docs/`, and the
      changelog.
