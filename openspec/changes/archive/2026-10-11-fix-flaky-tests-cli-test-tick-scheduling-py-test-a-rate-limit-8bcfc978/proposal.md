## Why

`tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_ends_at_its_deadline_within_the_pass` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
trees/agent-build-kit/spec_local_forge_3/.venv/bin/python

builder = <test_tick_scheduling.Builder object at 0x79c180659a30>
tmp_path = PosixPath('/tmp/pytest-of-<redacted>/pytest-3907/popen-gw1/test_a_rate_limit_pause_ends_a0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x79c17fcbd010>

    def test_a_rate_limit_pause_ends_at_its_deadline_within_the_pass(
        builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stop is worked out again each round from the marker: once the deadline has
        passed, the ready unit is submitted by the same pass, not held back by a flag the
        refusal set."""
        inst = workspace(tmp_path, max_concurrent=2)
        builder.store.upsert([stored("mid/1"), stored("slow/1", repo="platform"), stored("later/1")])
        monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
        marker = tmp_path / "paused.json"

        ends: list[datetime] = []

        def refused_by_the_model() -> None:
            # Written whole, as a pause is, but ending in a moment: the grace a recorded
            # pause adds would outlast the test.
            ends.append(datetime.now(UTC) + timedelta(seconds=0.5))
            marker.write_text(
                json.dumps(
                    {
                        "until": ends[0].isoformat(),
                        "reason": "the model refused",
                        "kind": "rate_limit",
                        "at": datetime.now(UTC).isoformat(),
                    }
                )
            )

        builder.scripts["mid/1"] = refused_by_the_model
        submitted: list[datetime] = []
        builder.scripts["later/1"] = lambda: submitted.append(datetime.now(UTC))
        builder.scripts["slow/1"] = lambda: (
            None if eventually(lambda: "later/1" in builder.finished) else "failed"
        )

        assert tick(inst) == 0

        assert "later/1" in builder.started, "the pass stayed stopped after the deadline"
>       assert submitted and submitted[0] >= ends[0], "the pass started it while the pause held"
E       AssertionError: the pass started it while the pause held
E       assert ([datetime.datetime(2026, 10, 11, 5, 30, 3, 683776, tzinfo=datetime.timezone.utc)] and datetime.datetime(2026, 10, 11, 5, 30, 3, 683776, tzinfo=datetime.timezone.utc) >= datetime.datetime(2026, 10, 11, 5, 30, 3, 977049, tzinfo=datetime.timezone.utc))

tests/cli/test_tick_scheduling.py:1867: AssertionError
----------------------------- Captured stdout call -----------------------------
[23:30:03] plenty
[23:30:03] ready: mid/1, slow/1
[23:30:03] mid/1: open — open mid/1
[23:30:03] ready: later/1
[23:30:03] later/1: open — open later/1
[23:30:03] slow/1: open — open slow/1
=============================== warnings summary ===============================
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
  /home/<redacted>/.local/share/uv/python/cpython-3.14.6-linux-x86_64-gnu/lib/python3.14/multiprocessing/popen_fork.py:76: DeprecationWarning: This process (pid=1461057) is multi-threaded, use of fork() may lead to deadlocks in the child.
    self.pid = os.fork()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_ends_at_its_deadline_within_the_pass
1 failed, 5646 passed, 4 warnings in 142.91s (0:02:22)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/cli/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/graph/checkpointer.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/installation.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/pipeline/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/pipeline/stack_runner.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/pipeline/unit_store.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/pipeline/units.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/pipeline/usage_guard.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/pipeline/wiring.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/pipeline/workspaces.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/src/agent_build_kit/settings.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/tests/conftest.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/tests/factories.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_local_forge_3/tests/runtimes/selectable.py`.

Times it flaked:

- 2026-10-11 05:31 UTC, unit local-forge/3 (this one)

## What Changes

- `tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_ends_at_its_deadline_within_the_pass` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
