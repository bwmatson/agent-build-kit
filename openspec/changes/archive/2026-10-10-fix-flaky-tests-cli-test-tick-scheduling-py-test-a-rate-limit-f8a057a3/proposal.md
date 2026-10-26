## Why

`tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_still_stops_new_builds_for_the_pass` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
..... [ 82%]
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
........................................................................ [ 99%]
..........................................                               [100%]
=================================== FAILURES ===================================
_________ test_a_rate_limit_pause_still_stops_new_builds_for_the_pass __________
[gw2] linux -- Python 3.14.6 /home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/.venv/bin/python

builder = <test_tick_scheduling.Builder object at 0x7a7e5b13be30>
tmp_path = PosixPath('/tmp/pytest-of-<redacted>/pytest-3254/popen-gw2/test_a_rate_limit_pause_still_0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7a7e584de040>

    def test_a_rate_limit_pause_still_stops_new_builds_for_the_pass(
        builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only a usage pause is the unit's. The model's own refusal says nothing
        about the usage endpoint, so it holds every start until its deadline."""
        inst = workspace(tmp_path, max_concurrent=2)
        builder.store.upsert([stored("mid/1"), stored("slow/1", repo="platform"), stored("later/1")])
        monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
        marker = tmp_path / "paused.json"
        looks: list[int] = []
        real_is_paused = cli.is_paused

        def counting(state):
            if "mid/1" in builder.finished:
                looks.append(1)
            return real_is_paused(state)

        monkeypatch.setattr(cli, "is_paused", counting)

        def refused_by_the_model() -> None:
            pause.pause_until(
                datetime.now(UTC) + timedelta(hours=1),
                reason="the model refused",
                marker=marker,
                kind="rate_limit",
            )

        builder.scripts["mid/1"] = refused_by_the_model
        # Rounds that went on after the refusal, not a wait of fixed length.
        builder.scripts["slow/1"] = lambda: None if eventually(lambda: len(looks) >= 3) else "failed"

        assert tick(inst) == 0

>       assert set(builder.started) == {"mid/1", "slow/1"}
E       AssertionError: assert {'later/1', 'mid/1', 'slow/1'} == {'mid/1', 'slow/1'}
E
E         Extra items in the left set:
E         'later/1'
E         Use -v to get more diff

tests/cli/test_tick_scheduling.py:1776: AssertionError
----------------------------- Captured stdout call -----------------------------
[10:47:54] plenty
[10:47:54] ready: mid/1, slow/1
[10:47:54] mid/1: open — open mid/1
[10:47:54] ready: later/1
[10:47:54] later/1: open — open later/1
[10:47:54] slow/1: open — open slow/1
=========================== short test summary info ============================
FAILED tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_still_stops_new_builds_for_the_pass
1 failed, 5081 passed in 129.96s (0:02:09)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/cli/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/graph/checkpointer.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/installation.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/pipeline/__init__.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/pipeline/stack_runner.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/pipeline/unit_store.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/pipeline/units.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/pipeline/usage_guard.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/pipeline/wiring.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/pipeline/workspaces.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/src/agent_build_kit/settings.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/tests/conftest.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/tests/factories.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_usage_cost_and_context_are_recorded_3/tests/runtimes/selectable.py`.

Times it flaked:

- 2026-10-10 16:49 UTC, unit usage-cost-and-context-are-recorded/3 (this one)

## What Changes

- `tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_still_stops_new_builds_for_the_pass` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
