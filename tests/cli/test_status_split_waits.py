"""`abk status` lists the units a held e2e-test split keeps from starting, beside the other
wait reasons, and says when the split has been released and they start this round (spec:
split-start-gate)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.e2e_holds import remove_hold
from tests.conftest import make_installation, run_status
from tests.parked_split_support import hold
from tests.project_workspace import repos_declaring
from tests.split_start_support import fresh, gate_round, installation, round_ids, store_of

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    gate_round(monkeypatch)


def test_a_gated_unit_is_listed_with_the_split_and_the_reason_of_the_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=None)
    hold(inst, "acp")
    fresh(store_of(inst), "gated/1", "acp")

    lines = run_status(inst, monkeypatch, capsys)

    [waiting] = [line for line in lines if "waiting for e2e-test split acp" in line]
    assert "gated/1" in waiting and "(app)" in waiting
    assert "the usage window is spent" in waiting


def test_only_the_units_of_a_held_split_are_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=False)
    hold(inst, "claude_code")
    store = store_of(inst)
    fresh(store, "plain/1", "rest")
    fresh(store, "usable/1", "acp")
    fresh(store, "gated/1", "claude_code")

    lines = run_status(inst, monkeypatch, capsys)

    waiting = [line for line in lines if "waiting for e2e-test split" in line]
    assert len(waiting) == 1 and "gated/1" in waiting[0]


def test_a_unit_whose_split_was_released_reads_released_and_starting_this_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=None)
    hold(inst, "acp")
    store = store_of(inst)
    fresh(store, "gated/1", "acp")
    assert round_ids(inst, store) == [], "held: the round leaves it out and records why"
    remove_hold(inst.state_dir, "acp")

    lines = run_status(inst, monkeypatch, capsys)

    [released] = [line for line in lines if "gated/1" in line and "e2e-test split acp" in line]
    assert "released, starts this round" in released
    assert not any("gated/1" in line and "usage window" in line for line in lines)


def test_a_repo_with_several_projects_names_the_project_as_the_other_lines_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=True, repos=repos_declaring(tmp_path, "app", ("web", "api")))
    store = store_of(inst)
    fresh(store, "web/1", "acp", project="web")
    fresh(store, "root/1", "acp")

    lines = run_status(inst, monkeypatch, capsys)

    [web] = [line for line in lines if "web/1" in line and "e2e-test split acp" in line]
    [root] = [line for line in lines if "root/1" in line and "e2e-test split acp" in line]
    assert "(app/web)" in web
    assert "(app)" in root and "(app/" not in root


def test_a_workspace_that_declares_no_split_shows_no_split_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    store = store_of(inst)
    fresh(store, "plain/1", "rest")
    round_ids(inst, store)

    lines = run_status(inst, monkeypatch, capsys)

    assert not any("e2e-test split" in line for line in lines)
