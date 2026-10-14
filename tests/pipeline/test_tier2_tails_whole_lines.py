"""The tails tier 2 keeps of a long output are cut by the shared tail cut: at most
4000 characters, the end of the output kept, and every line whole.

The runner is the faked boundary; it answers with plain console text.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.pipeline.wiring import Tier2Session
from tests.factories import unit
from tests.tier2_base_fakes import Runs, branch, pytest_output, session
from tests.tier2_failure_fakes import checkout

BUDGET = 4000
ONE = "tests/far/test_one.py::test_one"
LINES = [f"console line {n:05d} of a long output" for n in range(600)]
LONG = "\n".join(LINES)


def assert_tail_of_whole_lines(kept: str, original: list[str]) -> None:
    assert 0 < len(kept) <= BUDGET
    assert kept.splitlines()[-1] == original[-1], "the end of the output is kept"
    assert set(kept.splitlines()) <= set(original), "no line starts or ends in the middle"


def test_the_dev_stack_output_is_a_tail_of_whole_lines(tmp_path: Path) -> None:
    root = checkout(tmp_path)
    script = root / "scripts" / "dev-stack.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        out = f"{LONG}\n2 passed in 1.00s" if command[-1] == "test" else ""
        return subprocess.CompletedProcess(command, 0, out, "")

    gate = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=run,
        sha=lambda cwd: "abc1234",
    )

    gate.run(cwd=root)

    assert gate.result is not None
    assert_tail_of_whole_lines(gate.result.output, [*LINES, "2 passed in 1.00s"])


def test_the_base_output_is_a_tail_of_whole_lines(tmp_path: Path) -> None:
    repo, base_sha = branch(tmp_path, {})
    failed = pytest_output(failed={ONE: "assert 1 == 2"})
    base = f"{LONG}\n{failed}"
    gate = session(tmp_path, Runs(repo, failed, base))

    gate.run(cwd=repo, base=base_sha)

    assert gate.verdict is not None
    assert_tail_of_whole_lines(gate.verdict.base_output, base.splitlines())
