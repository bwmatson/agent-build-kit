# Design

## What was checked, and where

Read-only against the agent-build-kit checkout.

- `tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call` builds `multiprocessing.get_context("fork")`,
  starts `ASKERS` (4) `Process`es running `asking_in_a_process(5, results)`, collects twenty answers from a `Queue` with a 30-second timeout and joins.
  Its assertions: the call file has exactly one line, no answer is `None`, `("live", 33)` is among them, every session is 14 or 33.
- `read_live_usage` (`pipeline/usage_guard.py`) is what the children run. What the processes share is **the cache file and its sibling `.lock`**, taken
  with `try_file_lock` (`flock`), under the state directory: `Path.home() / ".cache" / "agent-build-kit"` when no installation is active. The property
  under test is that the `flock` on that file lets one process call and the others read what it wrote. It is a property of the kernel's lock between
  processes.
- The parent's setup, from the `host` fixture (`tests/usage_host.py`, built in `tests/conftest.py`) and `slow_endpoint`: `HOME` and
  `CLAUDE_CODE_OAUTH_TOKEN` set in the environment; `usage_guard.CREDENTIALS_PATH` and `DEFAULT_ANCHOR_PATH` patched to files under the home;
  `urllib.request.urlopen` replaced by `slow_endpoint`'s function, which appends a line to the `calls` file and waits `CALL_SECONDS` (0.4) on an event;
  `time.sleep` replaced by a no-op; `config.activate(WorkspaceConfig(), None)`; the logged-failures set cleared; and a seeded cache file 20 minutes old.
- `pyproject.toml` has `[tool.pytest.ini_options]` with `markers`, `addopts = "-m 'not integration and not local_stack'"` and no `filterwarnings`. The
  parallel pass is `pytest -n auto --maxprocesses=8 -m 'not serial ...'`, so the runner is multi-threaded (xdist's workers); `serial` is a registered marker
  that selects a second, non-parallel pass.
- Run read-only on this machine, `uv run pytest -q -W error::DeprecationWarning tests/pipeline/test_usage_one_authority.py -k several_processes` passes
  under Python 3.12.13: a serial single-file run has no extra threads, so the warning does not appear. The warning is therefore a property of the
  parallel runner, and the test must supply its own thread to reproduce it (below).

UNVERIFIED: that the CI warning goes away with `spawn`; it is reasoned from the cause, and the builder confirms it by running the test under the
parallel runner with the filter in place.

UNVERIFIED: what other warnings the whole suite emits today. The whole suite was not run. That is why the filter below is scoped to this message and not
to every `DeprecationWarning`.

## Choice: `spawn`, with a helper module

Three ways to keep the property were weighed.

**Recommended: (a) `multiprocessing.get_context("spawn")`.** A spawned child is a fresh interpreter that imports the target by name; it copies no
locks and no threads, so the warning's cause cannot exist. It keeps `multiprocessing.Queue`, `Process` and the timeouts the test already uses, so the
assertions stay as they are. It works the same on 3.11, 3.12 and 3.14 (3.14 makes `forkserver` the Linux default; `spawn` is the one start method that
behaves identically on every platform and version). `forkserver` is the near alternative and also avoids the warning, but it forks from a server
process that is started once, adds a third moving part, and gives no benefit for four short-lived children.

**(b) `subprocess` children running a helper module** is also correct and needs no pickling, but the test would then hand-build a command line, a result
channel (pipes or files) and its own timeouts to get what `Queue` and `Process` already give. More code, same property. Rejected.

**(c) Threads instead of processes** are rejected. The sibling test `test_several_threads_at_expiry_make_one_call_and_the_rest_are_served_the_last_good`
already covers threads. What this test adds is that the guarantee holds *between processes*: a separate `open` file description per process and the
kernel's `flock`, not an in-process lock and not shared module state. Threads in one process would pass for reasons that say nothing about that, and
would also share the monkeypatched `urlopen` and config, which the real askers do not.

### The helper module

`tests/usage_asker.py` (the same place and style as `tests/usage_host.py`, importable as `tests.usage_asker` because `pythonpath = ["."]`) holds
`asking_in_a_process(asks, results, setup)`, which is what the children run, and the function that makes the endpoint. `slow_endpoint` in the test file
and the child both build the slow `urlopen` from it, so there is one definition. A spawned child imports that module by name and never imports the test
file or `conftest.py`, which is why the function cannot stay in the test file as it is today (a function in a test module is importable by spawn only
through pytest's path handling, and the child would then import the whole test module and its fixtures).

### What the children must rebuild

A forked child inherited the parent's patched state. A spawned child inherits **only the environment variables** and what it is handed. Exactly:

| Parent set up | Spawned child | How |
|---|---|---|
| `HOME` (monkeypatch env) and `CLAUDE_CODE_OAUTH_TOKEN` | **inherited** (a child copies the parent's `os.environ` at start) | nothing; the cache lives under `HOME`, so both sides use the same file and lock |
| `urllib.request.urlopen` replaced by the slow endpoint | **lost** | rebuilt in the child from the `calls` path, the answer (`session=33.0`) and `CALL_SECONDS`, passed as plain arguments |
| `usage_guard.CREDENTIALS_PATH`, `DEFAULT_ANCHOR_PATH` patched | **lost** | rebuilt from the home path argument; with the token in the environment they are not read, but the child sets them so it does not touch the developer's own files |
| `config.activate(WorkspaceConfig(), None)` | **lost** (a child's config is unset) | the child activates the same default config |
| `time.sleep` replaced by a no-op | **lost** | not rebuilt: the only sleep in `read_live_usage` is the retry delay after a timeout or connection error, which the slow endpoint never raises. A child that did reach it would sleep for real, which is correct for a child |
| the logged-failures set cleared | **lost** (a fresh interpreter has it empty already) | nothing |
| the seeded cache file, 20 minutes old | **on disk**, so seen | nothing |
| the conftest's autouse guards (no real agent, no real `gh`, no real usage reader) | **lost** | not needed: the child imports `usage_guard`, not the adapter or the runner, and the only network path it can reach is the rebuilt `urlopen`. If the endpoint were not rebuilt the child would reach the real one, which is why the helper builds it before it asks and the test asserts the single recorded call |

The arguments are strings, numbers and paths, so they pickle; no fixture, `Host` or `monkeypatch` crosses the boundary. The helper reads no
setting from the environment of the pipeline beyond `HOME` and the token.

### The parent's thread, and determinism

Under the parallel runner the parent is multi-threaded; on a serial local run it is not, so a regression to `fork` would pass locally and warn only in CI.
The test therefore keeps one parked thread alive (`threading.Event().wait()` in a daemon thread, released and joined in a `finally`) while it starts the
askers. With that thread the old `fork` code warns on any machine, and with the filter below it fails there. This is the test that was red first.

Determinism rules from `test-determinism` and the suite's guards: no bare sleeps (the children wait on the endpoint's event and the queue, the parent on
`results.get(timeout=...)` and `join(timeout=...)`, as now); no fixed ports (there are none; the shared state is a file under the test's own `tmp_path`
home); every process is joined and a child left alive after the join is terminated, so none outlives the test. The test is **not `serial`**: it touches
only its own `tmp_path`, and a spawn costs an interpreter start per child, a second or two across the four, which the parallel pass absorbs. Marking it
`serial` would hide the property from the pass that has the threads. A builder who finds it slow under load raises the queue timeout, not the marker.

## The guard against regressions

`[tool.pytest.ini_options]` gains

```
filterwarnings = [
    "error:This process .* is multi-threaded, use of fork\\(\\) may lead to deadlocks in the child:DeprecationWarning",
]
```

**Recommended: scoped by message and category, not `error::DeprecationWarning` and not `-W error`.** The whole suite was not run for this change, and
third-party code (xdist, pytest plugins, the libraries the tests import) emits `DeprecationWarning`s the project does not control; a blanket `error` would turn
those into a red CI on every dependency bump for reasons that have nothing to do with the code. The scoped filter makes the exact class of warning that
was found a failure at the line that causes it, and everything else stays visible in the summary as now. A broader policy is a decision for after
someone has run the suite with `-W error` and read the list; it is not made here. The `error` entry is placed in the config, not in `addopts`, so
`pytest -W ...` on the command line can still override it.

The filter applies to warnings raised in the process that runs the test; a child's own warnings are not seen by it, which is acceptable because the
children are spawned.

A test (`tests/test_warning_filters.py`, beside `tests/test_parallel_suite.py`, which also reads `pyproject.toml`) asserts the entry is present: it loads
`[tool.pytest.ini_options]`, finds a `filterwarnings` entry that begins with `error` and matches a sample of the real warning text, and fails
with the entry that is missing. It also asserts the behaviour, not only the text: with the filter applied through `pytester`, a test that forks while another
thread is alive fails, and one that spawns passes. UNVERIFIED: that `pytester` (already in `pytest_plugins`) can run the filter from a `pyproject.toml`
it writes; the builder may instead use `warnings.filterwarnings` with the parsed entry in-process.

## No changelog

`AGENTS.md`'s changelog rule is for a change "someone using the tool sees". This one changes a test, a test helper and pytest's options in the repo; the
tool's behaviour is unchanged. No `CHANGELOG.md` entry, no `docs/` page, no skill text.

## Not included

A blanket `error` policy for warnings, a `-W error` pass of the whole suite, other tests that fork (none were looked for: UNVERIFIED that no other test
uses `get_context("fork")` or `os.fork`; the builder greps `tests/` and, if one exists, moves it the same way in this change), and any change to
`usage_guard`.
