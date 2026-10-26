## Why

`tests/cli/test_tick_committed_marker.py::test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
aller that has its own.
        """
        read = read or current_usage
        judge = decide or may_start_unit

        def carrying(decision: Decision, reading: UsageReading | None) -> Decision:
            if decision.resets_at is None and reading is not None:
                return decision.model_copy(update={"resets_at": reading.resets_at})
            return decision

        def fresh() -> Decision:
            reading = read()
            return carrying(judge(reading), reading)

        now = datetime.now(UTC)
        cache_path = _cache_file()
        calls_file = cache_path.parent / CALLS_NAME
        held = _kept_reading(_load_cache(cache_path))
        if held is not None and not _past_reset(held, now):
>           decision = carrying(judge(held, trust_age=True), held)
                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           TypeError: isolated.<locals>.<lambda>() got an unexpected keyword argument 'trust_age'

src/agent_build_kit/pipeline/usage_guard.py:1007: TypeError
----------------------------- Captured stdout call -----------------------------
[08:52:40] plenty
[08:52:40] feature/1: await_review: started
[08:52:40] feature/1: await_review: adopted: commit d11b4056e
[08:52:40] label: setting running on #7 failed - AssertionError: a test tried to run a real gh command: gh auth token --user example
[08:52:40] draft: setting #7 to draft=True failed - AssertionError: a test tried to run a real gh command: gh auth token --user example
[08:52:40] feature/1: adopted delivered: open — adopted delivered; checks runs next
[08:52:40] feature/1: commit d11b4056e delivered
[08:52:40] ready: feature/1
[08:52:40] feature/1: checks: started
[08:52:40] feature/1: checks: checks before review
[08:52:40] feature/1:   tier 1: uv run pre-commit run --from-ref main --to-ref HEAD (in /tmp/pytest-of-<redacted>/pytest-3132/popen-gw2/trees/app/spec_feature_1) exit 1, 0s
[08:52:40] feature/1: checks: checks failed
[08:52:40] feature/1: checks: $ uv run pre-commit run --from-ref main --to-ref HEAD (exit 1)
An error has occurred: InvalidConfigError:
=====> .pre-commit-<redacted> is not a file
Check the log at /home/<redacted>/.cache/pre-commit/pre-commit.log
[08:52:41] feature/1: fix_checks: started
[08:52:41] feature/1: fix_checks: fix the failing checks (opus), round 1
[08:52:41] feature/1: fix_checks: the build session cannot be continued (the commit abc123 it last saw is gone from the worktree); running the node from its start in a new session
[08:52:41] feature/1: failed, AssertionError: a test tried to spawn a real agent process — inject `execute=`
[08:52:41] label: setting failed on #7 failed - AssertionError: a test tried to run a real gh command: gh auth token --user example
=============================== warnings summary ===============================
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
  /home/<redacted>/.local/share/uv/python/cpython-3.14.6-linux-x86_64-gnu/lib/python3.14/multiprocessing/popen_fork.py:76: DeprecationWarning: This process (pid=2416278) is multi-threaded, use of fork() may lead to deadlocks in the child.
    self.pid = os.fork()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/cli/test_tick_committed_marker.py::test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease
1 failed, 4972 passed, 4 warnings in 115.38s (0:01:55)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/src/agent_build_kit/cli/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/src/agent_build_kit/installation.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/src/agent_build_kit/pipeline/lease.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/src/agent_build_kit/pipeline/stack_runner.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/src/agent_build_kit/pipeline/unit_store.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/src/agent_build_kit/pipeline/units.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/src/agent_build_kit/pipeline/usage_guard.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/tests/attach_driver.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/tests/chat_serving.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/tests/conftest.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_pause_deadline_4/tests/factories.py`.

Times it flaked:

- 2026-10-10 14:54 UTC, unit usage-pause-deadline/4 (this one)

## What Changes

- `tests/cli/test_tick_committed_marker.py::test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
