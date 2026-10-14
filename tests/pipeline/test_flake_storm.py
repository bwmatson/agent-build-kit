"""Many flaky tests in one run are one storm, recorded once and fixed by no change
(spec: flake-storm).

Tier 1 runs for real over a fake runner that answers as the processes would (see
`test_flake_isolation`). The storm row is read back from the record's file as it is written,
a JSON line with `kind: "storm"`.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import Flake, FlakeFound, flake_record
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.base import ToolchainProfile
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.pipeline.test_flake_isolation import FAILED, HookedProfile, Runs
from tests.storm_fakes import AfterTheStorm, ManyFailed, ThenFailing

COMMAND = "uv run pytest -n auto -q"


def storms(installation: Installation) -> list[dict]:
    """The storm rows of the flake record, as written."""
    try:
        lines = flake_record(installation).path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    rows = [json.loads(line) for line in lines if line.strip()]
    return [row for row in rows if row.get("kind") == "storm"]


def tier1(profile: object, runs: Runs, tmp_path: Path) -> tuple[bool, str]:
    return build_tier1(
        profile=cast(ToolchainProfile, profile), run=runs, changed=lambda *a: ["tests/test_one.py"]
    )(cwd=tmp_path, base="main")


def test_flakes_over_the_limit_are_one_storm_and_tier_1_goes_on(tmp_path: Path) -> None:
    installation = make_installation(tmp_path, global_limits=dict(max_flakes_per_run=2))

    passed, output = tier1(HookedProfile(), Runs(reruns=[0, 0]), tmp_path)

    assert (passed, output) == (True, "")
    (storm,) = storms(installation)
    assert storm["count"] == len(FAILED)
    assert storm["tests"] == FAILED
    assert storm["command"] == COMMAND
    assert flake_record(installation).entries() == [], "no per-test entry"


def test_a_storm_does_not_cut_tier_1_short(tmp_path: Path) -> None:
    installation = make_installation(tmp_path, global_limits=dict(max_flakes_per_run=2))
    runs = AfterTheStorm(reruns=[0, 0])

    passed, output = tier1(ThenFailing(), runs, tmp_path)

    assert not passed
    assert "second" in output and "an assertion failed" in output
    assert ["second"] in runs.commands, "the command after the stormed one ran"
    assert len(storms(installation)) == 1


def test_ninety_seven_flakes_are_one_storm_naming_the_first_ten(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)

    passed, _ = tier1(ManyFailed(), Runs(reruns=[0, 0]), tmp_path)

    assert passed
    (storm,) = storms(installation)
    assert storm["count"] == 97
    assert storm["tests"] == [f"test_one.py::test_case_{number:03}" for number in range(10)]


def test_flakes_at_the_limit_are_handled_one_by_one_and_no_storm_is_recorded(
    tmp_path: Path,
) -> None:
    installation = make_installation(tmp_path, global_limits=dict(max_flakes_per_run=len(FAILED)))

    with pytest.raises(FlakeFound) as found:
        tier1(HookedProfile(), Runs(reruns=[0, 0]), tmp_path)

    assert [flake.test for flake in found.value.flakes] == FAILED
    assert storms(installation) == []


def test_status_shows_a_storm_as_one_line_and_not_in_the_per_test_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    UnitStore(tmp_path / "units.json").upsert([stored_unit("one/1", change="one")])
    record = flake_record(workspace)
    record.append(
        Flake(
            test="tests/test_a.py::test_x",
            unit="one/1",
            command=COMMAND,
            output="FAILED",
            at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
            change="fix-flaky-test-x",
        )
    )
    storm = {
        "kind": "storm",
        "unit": "one/1",
        "at": "2026-03-01T09:30:00Z",
        "count": 97,
        "tests": [f"tests/test_widget.py::test_case_{number:03}" for number in range(10)],
        "command": COMMAND,
    }
    with record.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(storm) + "\n")
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    (line,) = [ln for ln in lines if "storm" in ln]
    assert "97" in line
    assert not any("test_case_000" in ln for ln in lines), "its tests are not listed one by one"
    assert any("tests/test_a.py::test_x" in ln and "flaky" in ln for ln in lines)
