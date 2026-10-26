## Why

`tests/runtimes/test_policy_agent_harness.py::test_a_command_refused_without_a_terminal_request_is_refused_and_one_run_is_reached` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
........................................................................ [ 88%]
........................................................................ [ 89%]
........................................................................ [ 90%]
........................................................................ [ 90%]
........................................................................ [ 91%]
............s........................................................... [ 92%]
........................................................................ [ 93%]
........................................................................ [ 93%]
........................................................................ [ 94%]
........................................................................ [ 95%]
........................................................................ [ 96%]
........................................................................ [ 96%]
........................................................................ [ 97%]
........................................................................ [ 98%]
........................................................................ [ 99%]
........................................................................ [ 99%]
.....                                                                    [100%]
=================================== FAILURES ===================================
_ test_a_command_refused_without_a_terminal_request_is_refused_and_one_run_is_reached _
[gw3] linux -- Python 3.14.6 /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_planning_in_the_working_copy_14/.venv/bin/python

record = PosixPath('/tmp/pytest-of-<redacted>/pytest-3393/popen-gw3/test_a_command_refused_without0/record')
scratch = PosixPath('/tmp/pytest-of-<redacted>/pytest-3393/popen-gw3/test_a_command_refused_without0/scratch')

    def test_a_command_refused_without_a_terminal_request_is_refused_and_one_run_is_reached(
        record: Path, scratch: Path
    ) -> None:
        result = drive(command(record, "judge", "--refuse", "git reset"), COMMANDS, deadline=30)

        assert result.finished
        assert {o.command: o.reached for o in result.observations} == {
            "git commit --no-verify -m probe": True,
            "git reset --hard HEAD": False,
            "git clean -fd": True,
        }
        assert [o.label for o in result.observations] == [label for _, label in COMMANDS]
        assert "git reset --hard HEAD" not in result.requested
>       assert_cleaned_up(record, scratch)

tests/runtimes/test_policy_agent_harness.py:177:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

record = PosixPath('/tmp/pytest-of-<redacted>/pytest-3393/popen-gw3/test_a_command_refused_without0/record')
scratch = PosixPath('/tmp/pytest-of-<redacted>/pytest-3393/popen-gw3/test_a_command_refused_without0/scratch')

    def assert_cleaned_up(record: Path, scratch: Path) -> None:
>       assert not [pid for pid in pids(record) if alive(pid)], "the agent's group is not gone"
E       AssertionError: the agent's group is not gone
E       assert not [2977974]

tests/runtimes/test_policy_agent_harness.py:54: AssertionError
----------------------------- Captured stderr call -----------------------------
policy harness: judged 1/3: git commit --no-verify -m probe (reached)
policy harness: judged 2/3: git reset --hard HEAD (refused)
policy harness: judged 3/3: git clean -fd (reached)
=========================== short test summary info ============================
FAILED tests/runtimes/test_policy_agent_harness.py::test_a_command_refused_without_a_terminal_request_is_refused_and_one_run_is_reached
1 failed, 9579 passed, 1 skipped in 286.10s (0:04:46)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_planning_in_the_working_copy_14/tests/runtimes/policy_agent_harness.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_planning_in_the_working_copy_14/tests/runtimes/policy_fake_agents.py`.

Times it flaked:

- 2026-10-16 20:38 UTC, unit planning-in-the-working-copy/14 (this one)

## What Changes

- `tests/runtimes/test_policy_agent_harness.py::test_a_command_refused_without_a_terminal_request_is_refused_and_one_run_is_reached` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
