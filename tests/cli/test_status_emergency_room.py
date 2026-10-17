"""`abk status` shows the emergency lane: a full project says a priority-0 unit may still start
while the lane has room, and `emergency room N/M used by <unit>` while a unit uses it.

Five places and four workers; the lane's cap is one unless a test says otherwise."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.conftest import run_status
from tests.emergency_lane_support import app_only_repos, build, lane_workspace, seeded
from tests.factories import stored_unit
from tests.project_workspace import repos_declaring
from tests.restack_lane_fakes import WAIT, Restacks, repo_behind

SENTENCE = "a priority-0 unit may still start"


def five_in_progress(*, lane_unit: str | None = None) -> list:
    """Five units in progress: four running (one of them the lane's, when named) and one in
    review."""
    running = [build(f"run{n}/1") for n in range(3 if lane_unit else 4)]
    if lane_unit:
        running.append(build(lane_unit, priority=0))
    return [*running, build("rev/1", IN_REVIEW)]


def full_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "queue is full" in line]


def room_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "emergency room" in line]


def test_a_full_project_with_the_lane_empty_says_a_priority_zero_unit_may_still_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = lane_workspace(tmp_path, repos=app_only_repos(tmp_path))
    seeded(inst, tmp_path, five_in_progress())

    lines = run_status(inst, monkeypatch, capsys)

    (full,) = full_lines(lines)
    assert SENTENCE in full
    assert room_lines(lines) == []


def test_a_unit_in_the_lane_is_named_and_the_sentence_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = lane_workspace(tmp_path, repos=app_only_repos(tmp_path))
    seeded(inst, tmp_path, five_in_progress(lane_unit="zero/1"), lane=["zero/1"])

    lines = run_status(inst, monkeypatch, capsys)

    assert len(room_lines(lines)) == 1
    assert "emergency room 1/1 used by zero/1" in room_lines(lines)[0]
    assert not any(SENTENCE in line for line in lines)


def test_a_restack_run_over_the_cap_is_not_a_use_of_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Four running builds and a unit being restacked by the restack lane fill the project's
    # five places and, with the restack, go past the four workers. The emergency lane's record
    # is empty, so the lane has room and no room line is printed.
    inst = repo_behind(
        tmp_path,
        monkeypatch,
        max_concurrent_stacks=4,
        max_units_in_progress=5,
        emergency_extra=1,
    )
    owed = "feature/3"
    store = seeded(
        inst,
        tmp_path,
        [*(build(f"run{n}/1") for n in range(4)), (stored_unit(owed, change="feature"), PLANNED)],
    )
    store.set_state(owed, PLANNED, branch="spec/feature/3", cause=Cause.BASE_CHANGED)
    moves = Restacks()

    with cli.build_restack_lane(inst, store) as lane:
        lane.hand_over(store.get(owed), partial(moves, store.get(owed)))
        assert moves.begun[owed].wait(WAIT)
        lines = run_status(inst, monkeypatch, capsys)
        moves.release_all()

    assert any(f"{owed}" in line and "restacking onto" in line for line in lines)
    assert room_lines(lines) == []
    assert any(SENTENCE in line for line in full_lines(lines))


def test_with_the_lane_off_nothing_about_the_lane_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    on = lane_workspace(tmp_path / "on", repos=app_only_repos(tmp_path / "on"))
    seeded(on, tmp_path / "on", five_in_progress())
    off = lane_workspace(tmp_path / "off", extra=0, repos=app_only_repos(tmp_path / "off"))
    seeded(off, tmp_path / "off", five_in_progress())

    with_lane = run_status(on, monkeypatch, capsys)
    without = run_status(off, monkeypatch, capsys)

    assert any(SENTENCE in line for line in with_lane)
    (full,) = full_lines(without)
    assert full.endswith("queue is full: 5 units in progress, limit 5 (1 in review, 4 running)")
    assert room_lines(without) == []


def test_each_project_of_a_workspace_names_itself_on_its_lane_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = lane_workspace(tmp_path, repos=repos_declaring(tmp_path, "app", ("web", "api")))
    web = [build(f"w{n}/1", project="web") for n in range(3)]
    api = [build(f"a{n}/1", project="api") for n in range(4)]
    seeded(
        inst,
        tmp_path,
        [
            *web,
            build("wzero/1", project="web", priority=0),
            build("wrev/1", IN_REVIEW, project="web"),
            *api,
            build("arev/1", IN_REVIEW, project="api"),
        ],
        lane=["wzero/1"],
    )

    lines = run_status(inst, monkeypatch, capsys)

    (room,) = room_lines(lines)
    assert "app/web" in room
    assert "emergency room 1/1 used by wzero/1" in room
    (api_full,) = [line for line in full_lines(lines) if "app/api" in line]
    assert SENTENCE in api_full
    (web_full,) = [line for line in full_lines(lines) if "app/web" in line]
    assert SENTENCE not in web_full
