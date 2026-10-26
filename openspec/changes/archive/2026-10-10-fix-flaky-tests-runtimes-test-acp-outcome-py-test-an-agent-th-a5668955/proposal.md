## Why

`tests/runtimes/test_acp_outcome.py::test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
..................................................... [ 71%]
........................................................................ [ 72%]
........................................................................ [ 73%]
........................................................................ [ 75%]
........................................................................ [ 76%]
........................................................................ [ 78%]
........................................................................ [ 79%]
....F................................................................... [ 80%]
........................................................................ [ 82%]
........................................................................ [ 83%]
........................................................................ [ 85%]
........................................................................ [ 86%]
........................................................................ [ 87%]
........................................................................ [ 89%]
........................................................................ [ 90%]
........................................................................ [ 92%]
........................................................................ [ 93%]
........................................................................ [ 94%]
........................................................................ [ 96%]
........................................................................ [ 97%]
........................................................................ [ 98%]
....................................................                     [100%]
=================================== FAILURES ===================================
_ test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed _
[gw0] linux -- Python 3.14.6 /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_environment_is_language_independent_3/.venv/bin/python

tmp_path = PosixPath('/tmp/pytest-of-<redacted>/pytest-3467/popen-gw0/test_an_agent_that_ends_its_tu0')
worktree = PosixPath('/tmp/pytest-of-<redacted>/pytest-3467/popen-gw0/test_an_agent_that_ends_its_tu0/worktree')
specs = PosixPath('/tmp/pytest-of-<redacted>/pytest-3467/popen-gw0/test_an_agent_that_ends_its_tu0/planning/openspec/specs')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7cbcc5ac9e10>

    def test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed(
        tmp_path: Path, worktree: Path, specs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The agent answers and exits, but a process it started in its group
        still holds stderr: the answer stands, and that process is killed rather
        than left running after the tick."""
        monkeypatch.setattr(acp, "EXIT_GRACE", 0.2)
        record = tmp_path / "agent.jsonl"
        use_agent(record, linger=True)

        result, elapsed = _run_bounded(_request(worktree, specs))
        child = int(orphan_pid_file(record).read_text())
        left = not _gone_soon(child)
        if left:
            _kill_if_left(child)

        assert result is not None, "run() did not return"
        assert elapsed < 5
        assert result.ok is True
        assert result.text == ANSWER
>       assert not left, "the agent's child outlived the run"
E       AssertionError: the agent's child outlived the run
E       assert not True

tests/runtimes/test_acp_outcome.py:501: AssertionError
=========================== short test summary info ============================
FAILED tests/runtimes/test_acp_outcome.py::test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed
1 failed, 5163 passed in 124.50s (0:02:04)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_environment_is_language_independent_3/src/agent_build_kit/runtimes/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_environment_is_language_independent_3/src/agent_build_kit/runtimes/acp.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_environment_is_language_independent_3/tests/runtimes/acp_agent.py`.

Times it flaked:

- 2026-10-10 18:57 UTC, unit environment-is-language-independent/3 (this one)

## What Changes

- `tests/runtimes/test_acp_outcome.py::test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
