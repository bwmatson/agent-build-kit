"""The tier 2 node hands the gate the base its run is against, so an untouched failing test
is rerun on that base (spec: tier2-failures)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.wiring import Tier2Session
from agent_build_kit.profiles.python_uv import PROFILE
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh
from tests.tier2_base_fakes import Runs, branch, pytest_output

FAILED = "tests/far/test_far.py::test_far"


def test_an_untouched_failing_test_is_rerun_on_the_base_the_node_runs_against(
    tmp_path: Path,
) -> None:
    repo, base_sha = branch(tmp_path, {})
    output = pytest_output(failed={FAILED: "assert 1 == 2"})
    runs = Runs(repo, output, output)
    gate = Tier2Session(
        unit(tier="tier2"), lock=tmp_path / "t2.lock", run=runs, sha=lambda cwd: "abc1234"
    )
    recorder = fresh(tmp_path, tier="tier2")

    build(
        tmp_path,
        recorder,
        base=base_sha,
        worktree=lambda *args, **kwargs: repo,
        run_tier2=gate.run,
    )

    assert runs.on_base == [PROFILE.serial_rerun_command(runs.on_unit[0], [FAILED])]
    assert runs.heads == [base_sha]
    assert gate.verdict is not None
    assert [f.test for f in gate.verdict.pre_existing] == [FAILED]
