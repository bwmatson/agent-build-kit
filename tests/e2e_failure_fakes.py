"""Recorded pytest output and the drivers the e2e-test failure listing tests share."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.unit import run_unit
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import E2eSession
from tests.factories import unit
from tests.runner_fakes import Recorder, make_runner

FIXTURE_LINE = "FileNotFoundError: [Errno 2] No such file or directory: 'svc-a'"

# Recorded from pytest 9.1.1 run as `pytest -vv -rfE --tb=short` with COLUMNS=80 and CI
# unset, over a module whose fixture fails for four tests. Only the paths are edited: the
# checkout's absolute path and the interpreter's are shortened.
FOUR_ERRORS = f"""\
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /usr/bin/python
rootdir: /work/app
plugins: anyio-4.15.1
collecting ... collected 6 items

tests/integration/test_unit.py::test_built ERROR [ 16%]
tests/integration/test_unit.py::test_pushed ERROR [ 33%]
tests/integration/test_unit.py::test_refused ERROR [ 50%]
tests/integration/test_unit.py::test_report ERROR [ 66%]
tests/integration/test_unit.py::test_alone PASSED [ 83%]
tests/integration/test_unit.py::test_other PASSED [100%]

==================================== ERRORS ====================================
_________________________ ERROR at setup of test_built _________________________
tests/integration/test_unit.py:6: in built
    raise FileNotFoundError("[Errno 2] No such file or directory: 'svc-a'")
E   {FIXTURE_LINE}
________________________ ERROR at setup of test_pushed _________________________
tests/integration/test_unit.py:6: in built
    raise FileNotFoundError("[Errno 2] No such file or directory: 'svc-a'")
E   {FIXTURE_LINE}
________________________ ERROR at setup of test_refused ________________________
tests/integration/test_unit.py:6: in built
    raise FileNotFoundError("[Errno 2] No such file or directory: 'svc-a'")
E   {FIXTURE_LINE}
________________________ ERROR at setup of test_report _________________________
tests/integration/test_unit.py:6: in built
    raise FileNotFoundError("[Errno 2] No such file or directory: 'svc-a'")
E   {FIXTURE_LINE}
=========================== short test summary info ============================
ERROR tests/integration/test_unit.py::test_built - {FIXTURE_LINE}
ERROR tests/integration/test_unit.py::test_pushed - {FIXTURE_LINE}
ERROR tests/integration/test_unit.py::test_refused - {FIXTURE_LINE}
ERROR tests/integration/test_unit.py::test_report - {FIXTURE_LINE}
========================= 2 passed, 4 errors in 0.03s ==========================
"""

# Recorded the same way: failures and errors mixed, and a parametrised id with a space.
MIXED = """\
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /usr/bin/python
rootdir: /work/app
plugins: anyio-4.15.1
collecting ... collected 4 items

tests/live/test_route.py::test_route FAILED [ 25%]
tests/live/test_route.py::test_param[a b] FAILED [ 50%]
tests/live/test_route.py::test_fixture ERROR [ 75%]
tests/live/test_route.py::test_ok PASSED [100%]

==================================== ERRORS ====================================
________________________ ERROR at setup of test_fixture ________________________
tests/live/test_route.py:6: in port
    raise KeyError("PORT")
E   KeyError: 'PORT'
=================================== FAILURES ===================================
__________________________________ test_route __________________________________
tests/live/test_route.py:10: in test_route
    assert 404 == 200
E   assert 404 == 200
_______________________________ test_param[a b] ________________________________
tests/live/test_route.py:15: in test_param
    raise ValueError("bad route")
E   ValueError: bad route
=========================== short test summary info ============================
FAILED tests/live/test_route.py::test_route - assert 404 == 200
FAILED tests/live/test_route.py::test_param[a b] - ValueError: bad route
ERROR tests/live/test_route.py::test_fixture - KeyError: 'PORT'
===================== 2 failed, 1 passed, 1 error in 0.03s =====================
"""

# A message of several lines is printed whole under -vv, so its later lines sit among the
# entries, one of them beginning with the word `ERROR`.
MULTILINE = """\
=========================== short test summary info ============================
FAILED tests/live/test_route.py::test_connect - AssertionError: connect failed
ERROR connecting to svc-a
assert 1 == 2
ERROR tests/live/test_route.py::test_fixture - KeyError: 'PORT'
========================= 2 failed in 0.03s =========================
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


def checkout(tmp_path: Path, *names: str) -> Path:
    """A checkout directory under `tmp_path` holding one directory per name."""
    root = tmp_path / "checkout"
    root.mkdir()
    for name in names:
        (root / name).mkdir()
    return root


def run_returning(*answers: str, code: int = 1):
    """A runner that answers its calls with `answers` in order (the last repeats)."""
    calls: list[str] = []

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        out = answers[min(len(calls), len(answers) - 1)]
        calls.append(" ".join(command))
        return subprocess.CompletedProcess(command, code, out, "")

    return run


def gate(tmp_path: Path, run, *, root: Path | None = None, **kwargs) -> E2eSession:
    """The e2e-test gate over a fake runner; with `root`, a project manifest is written there."""
    if root is not None:
        (root / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    return E2eSession(
        unit(tier="e2e-test"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=run,
        sha=lambda cwd: "abc1234",
        **kwargs,
    )


def run_failing_e2e(tmp_path: Path, snapshot: str) -> tuple[str, Path]:
    """Run an e2e-test unit whose e2e-test fails with `snapshot`: the feedback the unit
    holds afterwards, and the directory of its run logs."""
    logs = tmp_path / "unit-logs"
    e2e = unit(tier="e2e-test")
    run_log = RunLog(logs, e2e, step="build", model="m", base="main", started=datetime.now(UTC))
    store = UnitStore(tmp_path / "units.json")
    store.upsert([e2e])
    recorder = Recorder(store, e2e_ok=False)
    recorder.e2e_output = snapshot
    runner = make_runner(store, recorder, tmp_path)

    async def go() -> None:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            await run_unit(
                runner, e2e, base="main", graph=[], saver=saver, run_log=run_log, tracer=None
            )

    asyncio.run(go())
    return store.get(e2e.id).feedback, logs
