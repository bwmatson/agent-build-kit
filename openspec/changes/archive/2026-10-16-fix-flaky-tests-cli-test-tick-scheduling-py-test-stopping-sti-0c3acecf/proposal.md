## Why

`tests/cli/test_tick_scheduling.py::test_stopping_still_awaits_the_builds_in_flight` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
........................................................................ [ 89%]
........................................................................ [ 89%]
......................................................................s. [ 90%]
........................................................................ [ 91%]
........................................................................ [ 92%]
........................................................................ [ 92%]
........................................................................ [ 93%]
........................................................................ [ 94%]
........................................................................ [ 95%]
........................................................................ [ 96%]
........................................................................ [ 96%]
........................................................................ [ 97%]
........................................................................ [ 98%]
........................................................................ [ 99%]
........................................................................ [ 99%]
...................                                                      [100%]
=================================== FAILURES ===================================
_______________ test_stopping_still_awaits_the_builds_in_flight ________________
[gw3] linux -- Python 3.14.6 /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/.venv/bin/python

builder = <tests.tick_pass.Builder object at 0x7227121d5760>
tmp_path = PosixPath('/tmp/pytest-of-<redacted>/pytest-3180/popen-gw3/test_stopping_still_awaits_the0')

    def test_stopping_still_awaits_the_builds_in_flight(builder: Builder, tmp_path: Path) -> None:
        """What stops is submission. A build already running checks the guard
        itself, and killing it would leave its work uncommitted, so the pass
        waits for it to finish before returning."""
        inst = workspace(tmp_path, max_concurrent=2)
        builder.store.upsert(
            [
                stored("quick/1"),
                stored("slow/1", repo="platform"),
                stored("stops/1"),
                stored("later/1"),
            ]
        )

        def refused() -> None:
            pause.pause_until(
                datetime.now(UTC) + timedelta(hours=1),
                reason="the model refused",
                marker=tmp_path / "paused.json",
                kind="rate_limit",
            )

        builder.scripts["stops/1"] = refused
        builder.scripts["slow/1"] = lambda: wait_for(
            (tmp_path / "paused.json").exists, what="the pause file", timeout=WAIT
        )

        assert tick(inst) == 0

>       assert sorted(builder.started) == ["quick/1", "slow/1", "stops/1"]
E       AssertionError: assert ['later/1', '...1', 'stops/1'] == ['quick/1', '...1', 'stops/1']
E
E         At index 0 diff: 'later/1' != 'quick/1'
E         Left contains one more item: 'stops/1'
E         Use -v to get more diff

tests/cli/test_tick_scheduling.py:485: AssertionError
----------------------------- Captured stdout call -----------------------------
[13:01:10] plenty
[13:01:10] ready: quick/1, slow/1, stops/1
[13:01:10] quick/1: open — open quick/1
[13:01:10] stops/1: open — open stops/1
[13:01:10] slow/1: open — open slow/1
[13:01:10] ready: later/1
[13:01:10] later/1: open — open later/1
=========================== short test summary info ============================
FAILED tests/cli/test_tick_scheduling.py::test_stopping_still_awaits_the_builds_in_flight
1 failed, 9521 passed, 1 skipped in 180.11s (0:03:00)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/cli/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/installation.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/pipeline/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/pipeline/stack_runner.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/pipeline/unit_store.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/pipeline/units.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/pipeline/usage_guard.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/pipeline/wiring.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/pipeline/workspaces.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/src/agent_build_kit/settings.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/tests/conftest.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/tests/factories.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/tests/runtimes/selectable.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/tests/tick_driver.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/tests/tick_pass.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_limits_split_into_global_and_project_7/tests/waiting.py`.

Times it flaked:

- 2026-10-16 19:03 UTC, unit limits-split-into-global-and-project/7 (this one)

## What Changes

- `tests/cli/test_tick_scheduling.py::test_stopping_still_awaits_the_builds_in_flight` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
