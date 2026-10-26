## Why

`tests/pipeline/test_moved_base_run_stored.py::test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
........................................................................ [ 95%]
........................................................................ [ 95%]
........................................................................ [ 96%]
........................................................................ [ 97%]
........................................................................ [ 97%]
........................................................................ [ 98%]
........................................................................ [ 99%]
........................................................................ [ 99%]
.........                                                                [100%]
=================================== FAILURES ===================================
_ test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused _
[gw1] linux -- Python 3.14.6 /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_test_kinds_are_unit_test_and_e2e_test_21/.venv/bin/python

tmp_path = PosixPath('/tmp/pytest-of-<redacted>/pytest-4793/popen-gw1/test_a_running_pass_lets_a_han0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x785350bcef90>

    def test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        builder: Builder = install_builder(tmp_path, monkeypatch)
        inst = workspace(tmp_path, max_concurrent=3)
        builder.store.upsert([stored("back/1"), stored("usage/1"), stored("slow/1", repo="platform")])
        refreshes = count_refreshes(monkeypatch)
        runs: list[int] = []

        def held_once() -> str | None:
            runs.append(1)
            return "held" if len(runs) == 1 else None

        builder.scripts["back/1"] = held_once
        builder.ends["back/1"] = (PLANNED, Cause.RESTACK_HANDED_BACK, "handed back")
        builder.ends["usage/1"] = (PLANNED, Cause.USAGE, "usage")
        builder.scripts["usage/1"] = lambda: "held"

        def slow() -> str | None:
            wait_for(
                lambda: builder.started.count("back/1") == 2,
                what="back/1 to be started a second time",
                timeout=WAIT,
            )
            refreshes.wait_for(refreshes.count + SEVERAL_REFRESHES, timeout=WAIT)
            return None

        builder.scripts["slow/1"] = slow

        assert tick(inst) == 0

>       assert builder.started.count("back/1") == 2
E       AssertionError: assert 1 == 2
E        +  where 1 = <built-in method count of list object at 0x785350bb3080>('back/1')
E        +    where <built-in method count of list object at 0x785350bb3080> = ['back/1', 'usage/1', 'slow/1'].count
E        +      where ['back/1', 'usage/1', 'slow/1'] = <tests.tick_pass.Builder object at 0x785350e4ba70>.started

tests/pipeline/test_moved_base_run_stored.py:125: AssertionError
----------------------------- Captured stdout call -----------------------------
[21:54:07] plenty
[21:54:07] ready: back/1, usage/1, slow/1
[21:54:07] back/1: held — held back/1
[21:54:07] usage/1: held — held usage/1
[21:54:07] ready: back/1
[21:54:07] back/1: skipped, spec/back/1 is held by pid 1906289 since <date>T03:54:07.804835+00:00
[21:54:07] usage/1: not started again in this pass, stopped for usage
[21:54:38] slow/1: failed, TimeoutError: timed out after 30 seconds waiting for back/1 to be started a second time
=========================== short test summary info ============================
FAILED tests/pipeline/test_moved_base_run_stored.py::test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused
1 failed, 10447 passed, 1 skipped in 258.14s (0:04:18)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_test_kinds_are_unit_test_and_e2e_test_21/src/agent_build_kit/cli/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_test_kinds_are_unit_test_and_e2e_test_21/src/agent_build_kit/pipeline/unit_store.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_test_kinds_are_unit_test_and_e2e_test_21/src/agent_build_kit/pipeline/units.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_test_kinds_are_unit_test_and_e2e_test_21/tests/factories.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_test_kinds_are_unit_test_and_e2e_test_21/tests/tick_driver.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_test_kinds_are_unit_test_and_e2e_test_21/tests/tick_pass.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_test_kinds_are_unit_test_and_e2e_test_21/tests/waiting.py`.

Times it flaked:

- 2026-10-18 03:57 UTC, unit test-kinds-are-unit-test-and-e2e-test/21 (this one)

## What Changes

- `tests/pipeline/test_moved_base_run_stored.py::test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
