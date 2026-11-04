"""`abk status` prints the emergency lane's use `N/M` for each account that sets an
`emergency_extra`, beside each project's line, and says a priority-0 unit may still start only
while both the project's and the account's lane have room (spec: account-project-limits).

Three repos run on the account `kit`, each project's lane is one place unless a test says otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.cli.test_account_stack_cap_tick import workspace
from tests.conftest import run_status
from tests.emergency_lane_support import build, fresh, seeded
from tests.tick_pass import isolate

SENTENCE = "a priority-0 unit may still start"


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


def room_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "emergency room" in line]


def account_room_lines(lines: list[str]) -> list[str]:
    return [line for line in room_lines(lines) if "account kit: emergency room" in line]


def test_an_account_prints_its_lane_use_over_its_extra_and_the_units_using_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path, account={"emergency_extra": 3})
    seeded(
        inst,
        tmp_path,
        [
            build("a-zero/1", repo="app", priority=0),
            build("p-zero/1", repo="platform", priority=0),
        ],
        lane=["a-zero/1", "p-zero/1"],
    )

    lines = run_status(inst, monkeypatch, capsys)

    (line,) = account_room_lines(lines)
    assert "emergency room 2/3 used by" in line
    assert "a-zero/1" in line
    assert "p-zero/1" in line


def test_each_project_keeps_its_own_lane_line_beside_the_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path, account={"emergency_extra": 3})
    seeded(
        inst,
        tmp_path,
        [build("a-zero/1", repo="app", priority=0)],
        lane=["a-zero/1"],
    )

    lines = run_status(inst, monkeypatch, capsys)

    project_lines = [line for line in room_lines(lines) if "account kit" not in line]
    assert len(project_lines) == 1
    assert "emergency room 1/1 used by a-zero/1" in project_lines[0]
    assert len(account_room_lines(lines)) == 1


def test_an_account_that_sets_no_lane_extra_prints_no_account_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path, account={"max_units_in_progress": 20})
    seeded(inst, tmp_path, [build("a-zero/1", repo="app", priority=0)], lane=["a-zero/1"])

    lines = run_status(inst, monkeypatch, capsys)

    assert account_room_lines(lines) == []
    assert len(room_lines(lines)) == 1


def test_an_account_whose_lane_is_unused_prints_no_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path, account={"emergency_extra": 2})
    seeded(inst, tmp_path, [build("a-run/1", repo="app")])

    assert room_lines(run_status(inst, monkeypatch, capsys)) == []


def test_the_default_accounts_lane_use_is_not_an_account_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path, account={"emergency_extra": 2}, labels={"app": "kit"})
    seeded(inst, tmp_path, [build("w-zero/1", repo="web", priority=0)], lane=["w-zero/1"])

    lines = run_status(inst, monkeypatch, capsys)

    assert account_room_lines(lines) == []


def full_account(tmp_path: Path, *, account: dict) -> tuple[Installation, UnitStore]:
    """`kit` holds two units in progress, its limit: `a-rev/1` in review and `p-zero/1`, which uses
    the lane of `platform`; the lane of `app` is empty."""
    inst = workspace(tmp_path, account={"max_units_in_progress": 2, **account})
    store = seeded(
        inst,
        tmp_path,
        [build("a-rev/1", IN_REVIEW, repo="app"), build("p-zero/1", repo="platform", priority=0)],
        lane=["p-zero/1"],
    )
    return inst, store


def full_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "queue is full" in line]


def test_a_full_account_says_a_priority_zero_unit_may_still_start_while_both_lanes_have_room(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, _store = full_account(tmp_path, account={"emergency_extra": 2})

    (full,) = full_lines(run_status(inst, monkeypatch, capsys))

    assert SENTENCE in full


def test_a_full_account_with_its_lane_full_does_not_say_one_may_still_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `app`'s own lane is empty, but the account's one place is used by `platform`'s unit.
    inst, _store = full_account(tmp_path, account={"emergency_extra": 1})

    (full,) = full_lines(run_status(inst, monkeypatch, capsys))

    assert SENTENCE not in full


def test_a_full_account_with_its_extra_at_zero_does_not_say_one_may_still_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, _store = full_account(tmp_path, account={"emergency_extra": 0})

    (full,) = full_lines(run_status(inst, monkeypatch, capsys))

    assert SENTENCE not in full


def test_a_full_account_that_sets_no_lane_extra_keeps_the_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, _store = full_account(tmp_path, account={})

    (full,) = full_lines(run_status(inst, monkeypatch, capsys))

    assert SENTENCE in full


def held_back_reason(tmp_path: Path, *, account: dict) -> str:
    """What a pass that starts nothing says when `kit` is full and a unit waits for room."""
    inst, store = full_account(tmp_path, account=account)
    store.upsert([fresh("w-new/1", repo="web", priority=1)[0]])
    return cli._nothing_started_reason(inst, store.all(), only=frozenset())


def test_the_wait_wording_names_the_lane_when_the_accounts_lane_is_on(tmp_path: Path) -> None:
    reason = held_back_reason(tmp_path, account={"emergency_extra": 2})

    assert "except a ready priority-0 unit while the lane has room" in reason


def test_the_wait_wording_does_not_name_the_lane_when_the_accounts_extra_is_zero(
    tmp_path: Path,
) -> None:
    reason = held_back_reason(tmp_path, account={"emergency_extra": 0})

    assert "no new unit starts until one finishes or is closed" in reason
    assert "priority-0" not in reason
