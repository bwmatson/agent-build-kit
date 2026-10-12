"""Recorded pytest output and the drivers the tier 2 failure listing tests share."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.unit import run_unit
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import Tier2Session
from tests.factories import unit
from tests.runner_fakes import Recorder, make_runner

FIXTURE_LINE = "FileNotFoundError: [Errno 2] No such file or directory: 'svc-a'"

# `pytest -m local_stack -v -rfE --tb=short` over a module whose fixture fails for four
# tests: the verbose progress lines, the error sections and the short summary.
FOUR_ERRORS = f"""\
============================= test session starts ==============================
platform linux -- Python 3.13.1, pytest-8.3.4, pluggy-1.5.0 -- /usr/bin/python
cachedir: .pytest_cache
rootdir: /work/app
configfile: pyproject.toml
collecting ... collected 6 items / 0 deselected / 6 selected

tests/integration/test_unit.py::test_built ERROR                         [ 16%]
tests/integration/test_unit.py::test_pushed ERROR                        [ 33%]
tests/integration/test_unit.py::test_refused ERROR                       [ 50%]
tests/integration/test_unit.py::test_report ERROR                        [ 66%]
tests/integration/test_unit.py::test_alone PASSED                        [ 83%]
tests/integration/test_unit.py::test_other PASSED                        [100%]

==================================== ERRORS ====================================
_______________________ ERROR at setup of test_built ___________________________
tests/integration/test_unit.py:41: in built
    run(["svc-a"])
E   {FIXTURE_LINE}
=========================== short test summary info ============================
ERROR tests/integration/test_unit.py::test_built - {FIXTURE_LINE}
ERROR tests/integration/test_unit.py::test_pushed - {FIXTURE_LINE}
ERROR tests/integration/test_unit.py::test_refused - {FIXTURE_LINE}
ERROR tests/integration/test_unit.py::test_report - {FIXTURE_LINE}
=================== 2 passed, 4 errors in 8.31s ===================
"""

# Failures and errors mixed, a parametrised id with a space, and a failure whose
# traceback line also begins with the word FAILED.
MIXED = """\
============================= test session starts ==============================
collecting ... collected 4 items

tests/live/test_route.py::test_route FAILED                              [ 25%]
tests/live/test_route.py::test_param[a b] FAILED                         [ 50%]
tests/live/test_route.py::test_fixture ERROR                             [ 75%]
tests/live/test_route.py::test_ok PASSED                                 [100%]

=================================== FAILURES ===================================
_________________________________ test_route ___________________________________
tests/live/test_route.py:12: in test_route
    assert get("/health") == 200
E   AssertionError: assert 404 == 200
=========================== short test summary info ============================
FAILED tests/live/test_route.py::test_route - AssertionError: assert 404 == 200
ERROR tests/live/test_route.py::test_fixture - KeyError: 'PORT'
FAILED tests/live/test_route.py::test_param[a b] - ValueError: bad route
============== 2 failed, 1 error, 1 passed in 3.20s ==============
"""

NO_SUMMARY = (
    "tests/live/test_route.py::test_ok PASSED  [100%]\n\n======= 1 passed in 0.10s =======\n"
)

# What a node runner prints: no pytest short summary at all.
NODE_OUTPUT = """\
 FAIL  src/route.test.ts > route > answers
AssertionError: expected 404 to be 200
 Test Files  1 failed (1)
      Tests  1 failed | 2 passed (3)
"""


def run_returning(*answers: str, code: int = 1):
    """A runner that answers its calls with `answers` in order (the last repeats)."""
    calls: list[str] = []

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        out = answers[min(len(calls), len(answers) - 1)]
        calls.append(" ".join(command))
        return subprocess.CompletedProcess(command, code, out, "")

    return run


def gate(tmp_path: Path, run, **kwargs) -> Tier2Session:
    return Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=run,
        sha=lambda cwd: "abc1234",
        **kwargs,
    )


def feedback_after_failing_tier2(tmp_path: Path, snapshot: str) -> str:
    """The feedback the unit holds after a tier 2 that failed with `snapshot`."""
    logs = tmp_path / "unit-logs"
    tier_two = unit(tier="tier2")
    run_log = RunLog(
        logs, tier_two, step="build", model="m", base="main", started=datetime.now(UTC)
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([tier_two])
    recorder = Recorder(store, tier2_ok=False)
    recorder.tier2_output = snapshot
    runner = make_runner(store, recorder, tmp_path)

    async def go() -> None:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            await run_unit(
                runner, tier_two, base="main", graph=[], saver=saver, run_log=run_log, tracer=None
            )

    asyncio.run(go())
    return store.get(tier_two.id).feedback
