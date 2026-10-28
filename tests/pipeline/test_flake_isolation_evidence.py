"""Each serial rerun keeps its own evidence in the failing run's bundle, and a flake, a storm and a
pre-existing failure point at it (spec: test-failure-evidence).

Unit-test runs over the fake machine of `tests/failure_bundle_fakes.py`, which answers as the
processes would. The records are read back from their files as they are written. A row written
before the evidence existed is a JSON line without its three fields.
"""

from __future__ import annotations

import json
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.pipeline.flakes import Flake, FlakeFound
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_preexisting, build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.conftest import make_installation
from tests.e2e_gate_fakes import Planning
from tests.e2e_wait_fakes import OLD, verdict_of
from tests.failure_bundle_fakes import START, BundleMachine, BundleProfile
from tests.pipeline.test_flake_storm import storms
from tests.redaction_fakes import SECRET, known

RERUN_FILES = {"output.txt", "context.json", "machine.json", "worktree.json"}


def unit_test_of(scratch: Path, machine: BundleMachine, directory: Path):
    loads = iter(range(1, 100))
    clock = iter(START + timedelta(seconds=10 * n) for n in range(100))
    return build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=machine,
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=directory,
        now=lambda: next(clock),
        machine=lambda: {"load": [float(next(loads))] * 3},
    )


def flakes_of(scratch: Path, directory: Path, *, reruns: list[int]) -> tuple[Flake, ...]:
    with pytest.raises(FlakeFound) as found:
        unit_test_of(scratch, BundleMachine(scratch, reruns=reruns), directory)(
            cwd=scratch, base="main"
        )
    return found.value.flakes


def only_bundle(directory: Path) -> Path:
    (bundle,) = directory.iterdir()
    return bundle


def read(path: Path) -> dict:
    return json.loads(path.read_text())


# --- the reruns in the bundle ---------------------------------------------------------


def test_each_rerun_keeps_its_command_output_exit_times_and_its_own_machine_and_worktree(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"
    machine = BundleMachine(scratch, reruns=[0, 0])

    with pytest.raises(FlakeFound):
        unit_test_of(scratch, machine, directory)(cwd=scratch, base="main")

    reruns = only_bundle(directory) / "reruns"
    assert sorted(path.name for path in reruns.iterdir()) == ["1", "2"]
    serial = [c for c in machine.commands if any("::" in argument for argument in c)]
    for number, command in enumerate(serial, start=1):
        folder = reruns / str(number)
        assert {path.name for path in folder.iterdir()} == RERUN_FILES
        assert (folder / "output.txt").read_text().strip() == "1 passed"
        context = read(folder / "context.json")
        assert context["command"] == shlex.join(command)
        assert context["exit"] == 0
        assert datetime.fromisoformat(context["started"]) < datetime.fromisoformat(context["ended"])
        assert context["seconds"] > 0
        assert "load" in read(folder / "machine.json")["start"]
        assert "load" in read(folder / "machine.json")["end"]
        assert "status" in read(folder / "worktree.json")["before"]
        assert "status" in read(folder / "worktree.json")["after"]


def test_a_rerun_that_fails_is_kept_too_and_is_not_reduced_to_its_exit(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"

    passed, _ = unit_test_of(scratch, BundleMachine(scratch, reruns=[1, 1]), directory)(
        cwd=scratch, base="main"
    )

    assert not passed
    first = only_bundle(directory) / "reruns" / "1"
    assert read(first / "context.json")["exit"] == 1
    assert (first / "output.txt").read_text().strip() == "1 passed"


def test_a_rerun_s_files_are_redacted_like_the_rest_of_the_bundle(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"

    class Leaking(BundleMachine):
        def __call__(self, command: list[str], **kwargs: object):
            done = super().__call__(command, **kwargs)
            if any("::" in argument for argument in command):
                done.stdout = f"token={SECRET}\n"
            return done

    with known():
        with pytest.raises(FlakeFound):
            unit_test_of(scratch, Leaking(scratch, reruns=[0, 0]), directory)(
                cwd=scratch, base="main"
            )

    files = [path for path in (only_bundle(directory) / "reruns").rglob("*") if path.is_file()]
    assert files
    for path in files:
        assert SECRET not in path.read_text(), path


# --- the records ------------------------------------------------------------------------


def test_a_flake_row_names_the_bundle_the_start_and_the_conditions_and_keeps_its_clipped_fields(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"

    flakes = flakes_of(scratch, directory, reruns=[0, 0])

    bundle = only_bundle(directory)
    machine = read(bundle / "machine.json")
    assert len(flakes) == 5
    for flake in flakes:
        assert Path(flake.evidence) == bundle
        assert flake.ran_at == START, "when the first run started, not the verdict's time"
        assert flake.conditions["load_before"] == machine["start"]["load"][0]
        assert cast(float, flake.conditions["load_after"]) > cast(
            float, flake.conditions["load_before"]
        )
        assert flake.conditions["rerun_exits"] == [0, 0]
        seconds = cast(list[float], flake.conditions["rerun_seconds"])
        assert len(seconds) == 2 and all(taken > 0 for taken in seconds)
        assert "short test summary info" in flake.output, "the clipped output stays"
        assert flake.failure, "and the test's own section"


def test_the_bundle_is_pointed_at_so_it_is_kept(scratch: Path, tmp_path: Path) -> None:
    directory = tmp_path / "bundles"
    (flake, *_) = flakes_of(scratch, directory, reruns=[0, 0])

    assert Path(flake.evidence).is_dir()
    assert Path(flake.evidence).parent == directory


def test_a_storm_row_names_the_bundle_the_start_and_the_conditions(
    scratch: Path, tmp_path: Path
) -> None:
    installation = make_installation(scratch, global_limits=dict(max_flakes_per_run=2))
    directory = tmp_path / "bundles"

    passed, _ = unit_test_of(scratch, BundleMachine(scratch, reruns=[0, 0]), directory)(
        cwd=scratch, base="main"
    )

    assert passed
    (row,) = storms(installation)
    assert Path(row["evidence"]) == only_bundle(directory)
    assert datetime.fromisoformat(row["ran_at"]) == START
    assert row["conditions"]["rerun_exits"] == [0, 0]
    assert row["conditions"]["load_after"] > row["conditions"]["load_before"]
    assert row["failures"], "its clipped failures stay"


def test_a_pre_existing_row_carries_the_evidence_of_its_verdict(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD)
    unit = planning.store.get("feature/1")
    verdict = verdict_of(old=(OLD,)).model_copy(
        update={
            "evidence": "runs/e2e-output/feature-01-20260301-093000",
            "ran_at": datetime(2026, 3, 1, 9, 20, tzinfo=UTC),
            "conditions": {"load_before": 3.0, "load_after": 4.5},
        }
    )

    build_on_preexisting(planning.store, planning.installation, log=lambda m: None)(
        unit, verdict, verdict.pre_existing[0], wait=False
    )

    recorded = preexisting_record(planning.installation).entries()[-1]
    assert recorded.evidence == verdict.evidence
    assert recorded.ran_at == verdict.ran_at
    assert recorded.conditions == verdict.conditions
    assert recorded.base_output, "its clipped fields stay"
