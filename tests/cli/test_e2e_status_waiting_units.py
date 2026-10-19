"""`abk e2e-test status` lists under each held split the units waiting on it: the ones parked at
e2e-test and the ones not started (spec: split-start-gate)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import e2e_cmd
from tests.parked_split_support import hold, park
from tests.split_start_support import fresh, installation, store_of


def status(inst, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert e2e_cmd.cmd_e2e_status(argparse.Namespace(), inst) == 0
    return capsys.readouterr().out.splitlines()


def under(lines: list[str], split: str) -> list[str]:
    """The lines after `split`'s own, up to the next split's or the schedule's."""
    start = next(i for i, line in enumerate(lines) if line.startswith(split))
    rest = lines[start + 1 :]
    stop = next((i for i, line in enumerate(rest) if line and not line.startswith(" ")), len(rest))
    return rest[:stop]


def test_a_held_split_lists_its_parked_and_its_not_started_units_told_apart(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=None)
    hold(inst, "acp")
    store = store_of(inst)
    park(store, "parked/1", ("acp",))
    fresh(store, "gated/1", "acp")

    listed = under(status(inst, capsys), "acp")

    [parked] = [line for line in listed if "parked/1" in line]
    [gated] = [line for line in listed if "gated/1" in line]
    assert "(app)" in parked and "parked" in parked and "not started" not in parked
    assert "(app)" in gated and "not started" in gated and "parked" not in gated


def test_a_split_nothing_waits_on_lists_no_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=None)
    hold(inst, "acp")
    hold(inst, "claude_code")
    store = store_of(inst)
    fresh(store, "gated/1", "acp")

    lines = status(inst, capsys)

    assert any("gated/1" in line for line in under(lines, "acp"))
    assert not any("/1" in line for line in under(lines, "claude_code"))
    assert not any("rest" in line and "/1" in line for line in lines)


def test_the_lines_for_the_held_set_are_the_ones_it_printed_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=None)
    hold(inst, "acp")
    before = status(inst, capsys)
    fresh(store_of(inst), "gated/1", "acp")

    after = status(inst, capsys)

    assert [line for line in after if "gated/1" not in line] == before
    assert len(after) == len(before) + 1


def test_a_unit_of_a_repo_for_which_the_split_is_not_held_is_not_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repos = {
        "app": {"path": str(tmp_path / "checkouts" / "app"), "slug": "example/app"},
        "platform": {
            "path": str(tmp_path / "checkouts" / "platform"),
            "slug": "example/platform",
            "tests": {"e2e_splits": {}},
        },
    }
    inst = installation(tmp_path, acp=True, repos=repos)
    store = store_of(inst)
    fresh(store, "held/1", "acp", repo="app")
    fresh(store, "free/1", "acp", repo="platform")

    listed = under(status(inst, capsys), "acp")

    assert [line for line in listed if "/1" in line] == ["  not started: held/1 (app)"]
