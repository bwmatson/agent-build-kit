"""`abk status` shows each capped account's stacks and room, and the tick's sample row reports the
free workers as the lesser of the project's room and the account's room (spec:
account-project-limits).

The builds `abk status` cannot see in flight are units stored `running` whose branch lock is held,
as a build's is; the sample row is read from the ledger a tick writes, over builds that block.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.cli.test_account_stack_cap_tick import ready_in_each, workspace
from tests.conftest import run_status
from tests.emergency_lane_support import build, seeded
from tests.tick_pass import Builder, install_builder, isolate, warm_unit_graphs

pytestmark = pytest.mark.usefixtures("scripted_engine")

# Bounds the wait of a build when no sample row shows both running; a pass that has one never waits.
WAIT = 5


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)


def stacks_status(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    building: list[str],
) -> list[str]:
    """The lines of `abk status` with the branch lock of each unit in `building` held."""
    with ExitStack() as stack:
        for unit_id in building:
            stack.enter_context(
                branch_lock(store.get(unit_id).branch, root=inst.state_dir / "locks")
            )
        return run_status(inst, monkeypatch, capsys)


def test_a_capped_account_shows_its_stacks_building_and_the_room_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 3})
    store = seeded(
        inst,
        tmp_path,
        [
            build("app-run/1", repo="app"),
            build("platform-run/1", repo="platform"),
            *ready_in_each("web"),
        ],
    )

    lines = stacks_status(inst, store, monkeypatch, capsys, ["app-run/1", "platform-run/1"])

    [line] = [line for line in lines if "account kit: 2/3 stacks building" in line]
    assert "room 1" in line
    assert "max_concurrent_stacks" in line


def test_a_full_account_shows_no_room(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 2})
    store = seeded(
        inst,
        tmp_path,
        [
            build("app-run/1", repo="app"),
            build("platform-run/1", repo="platform"),
            *ready_in_each("web"),
        ],
    )

    lines = stacks_status(inst, store, monkeypatch, capsys, ["app-run/1", "platform-run/1"])

    [line] = [line for line in lines if "account kit: 2/2 stacks building" in line]
    assert "room 0" in line


def test_an_account_that_sets_no_stack_cap_shows_no_stacks_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path, account={"max_units_in_progress": 20})
    store = seeded(inst, tmp_path, [build("app-run/1", repo="app"), *ready_in_each("web")])

    lines = stacks_status(inst, store, monkeypatch, capsys, ["app-run/1"])

    assert not [line for line in lines if "stacks building" in line]


def test_the_default_account_shows_no_stacks_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 2}, labels={"app": "kit"})
    store = seeded(inst, tmp_path, [build("web-run/1", repo="web"), *ready_in_each("platform")])

    lines = stacks_status(inst, store, monkeypatch, capsys, ["web-run/1"])

    assert not [line for line in lines if "stacks building" in line]


def samples(directory: Path) -> list[dict]:
    path = directory / LEDGER_NAME
    lines = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [line for line in lines if line.get("kind") == "sample"]


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)
