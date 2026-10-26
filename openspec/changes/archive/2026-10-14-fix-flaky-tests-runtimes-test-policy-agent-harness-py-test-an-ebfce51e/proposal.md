## Why

`tests/runtimes/test_policy_agent_harness.py::test_an_agent_that_never_answers_ends_at_the_deadline_with_nothing_left` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
n 3.14.6 /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_policy_check_asks_the_agents_own_matcher_4/.venv/bin/python

record = PosixPath('/tmp/pytest-of-<redacted>/pytest-114/popen-gw3/test_an_agent_that_never_answe0/record')
scratch = PosixPath('/tmp/pytest-of-<redacted>/pytest-114/popen-gw3/test_an_agent_that_never_answe0/scratch')

    def test_an_agent_that_never_answers_ends_at_the_deadline_with_nothing_left(
        record: Path, scratch: Path
    ) -> None:
        started = time.monotonic()
        result = drive(command(record, "silent"), COMMANDS, deadline=DEADLINE)

        assert time.monotonic() - started < ENDS_WITHIN
        assert not result.finished
        assert result.error
        assert result.observations == ()
>       assert_cleaned_up(record, scratch)

tests/runtimes/test_policy_agent_harness.py:67:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
tests/runtimes/test_policy_agent_harness.py:53: in assert_cleaned_up
    assert not [pid for pid in pids(record) if alive(pid)], "the agent's group is not gone"
                               ^^^^^^^^^^^^
tests/runtimes/policy_fake_agents.py:59: in pids
    return [int((record / name).read_text()) for name in ("agent.pid", "child.pid")]
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^
../../../../uv/python/cpython-3.14.6-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:787: in read_text
    with self.open(mode='r', encoding=encoding, errors=errors, newline=newline) as f:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = PosixPath('/tmp/pytest-of-<redacted>/pytest-114/popen-gw3/test_an_agent_that_never_answe0/record/agent.pid')
mode = 'r', buffering = -1, encoding = 'locale', errors = None, newline = None

    def open(self, mode='r', buffering=-1, encoding=None,
             errors=None, newline=None):
        """
        Open the file pointed to by this path and return a file object, as
        the built-in open() function does.
        """
        if "b" not in mode:
            encoding = io.text_encoding(encoding)
>       return io.open(self, mode, buffering, encoding, errors, newline)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pytest-of-<redacted>/pytest-114/popen-gw3/test_an_agent_that_never_answe0/record/agent.pid'

../../../../uv/python/cpython-3.14.6-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:771: FileNotFoundError
----------------------------- Captured stderr call -----------------------------
policy harness: heartbeat: still waiting, 0/3 judged
=============================== warnings summary ===============================
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call
  /home/<redacted>/.local/share/uv/python/cpython-3.14.6-linux-x86_64-gnu/lib/python3.14/multiprocessing/popen_fork.py:76: DeprecationWarning: This process (pid=1401856) is multi-threaded, use of fork() may lead to deadlocks in the child.
    self.pid = os.fork()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/runtimes/test_policy_agent_harness.py::test_an_agent_that_never_answers_ends_at_the_deadline_with_nothing_left
1 failed, 7731 passed, 1 skipped, 4 warnings in 278.00s (0:04:37)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_policy_check_asks_the_agents_own_matcher_4/tests/runtimes/policy_agent_harness.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_policy_check_asks_the_agents_own_matcher_4/tests/runtimes/policy_fake_agents.py`.

Times it flaked:

- 2026-10-14 14:40 UTC, unit policy-check-asks-the-agents-own-matcher/4 (this one)

## What Changes

- `tests/runtimes/test_policy_agent_harness.py::test_an_agent_that_never_answers_ends_at_the_deadline_with_nothing_left` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
