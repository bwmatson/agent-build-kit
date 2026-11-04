"""A skip names the person by display name in the record and in `abk explain`, though the board
identifies them by a unique name that is an email address."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission_record import ADMISSIONS_NAME
from agent_build_kit.settings import settings
from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from agent_build_kit.trackers.config import AzureDevOpsTracker
from agent_build_kit.trackers.start_decision import start_decision
from tests.forges.conftest import PAT
from tests.split_start_support import fresh, gate_round, installation, round_ids, store_of
from tests.trackers.ado_work_item_host import WorkItemHost
from tests.trackers.board_support import CHANGE, board_section, covering
from tests.trackers.reconciler_support import World
from tests.trackers.start_support import FIRST, SECOND

pytestmark = pytest.mark.usefixtures("scripted_engine")

DISPLAY = "Alice Example"
UNIQUE = "alice@example.com"
WIRE_IDENTITY = {"displayName": DISPLAY, "uniqueName": UNIQUE, "id": "id-alice"}


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    gate_round(monkeypatch)
    yield
    trackers.unregister("azure_devops")


def azure_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[World, WorkItemHost, Installation]:
    """The Azure DevOps tracker over its HTTP stand-in, with the board pushed."""
    inst = installation(tmp_path, acp=True, project_limits={"max_units_in_progress": 5})
    # Activating the installation reloads the settings, so the credential is set after it.
    monkeypatch.setattr(settings, "ado_pat", PAT)
    clear_credentials()
    folder = inst.changes_dir.parent
    folder.mkdir(parents=True, exist_ok=True)
    host = WorkItemHost()
    section = board_section(["change", "group"])
    assert isinstance(section, AzureDevOpsTracker)
    world = World(folder, section, AzureDevOpsWorkItems(section, http=host))
    world.run([covering(FIRST, (1,)), covering(SECOND, (2,))])
    return world, host, inst


def test_a_skip_is_recorded_and_explained_by_display_name_never_the_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world, host, inst = azure_board(tmp_path, monkeypatch)
    host.edit(world.item_id(f"{CHANGE}:1"), assigned_to=WIRE_IDENTITY)
    store = store_of(inst)
    fresh(store, FIRST)

    assert round_ids(inst, store) == []

    written = (inst.state_dir / ADMISSIONS_NAME).read_text()
    assert DISPLAY in written
    assert UNIQUE not in written
    assert "@" not in written
    capsys.readouterr()
    assert cmd_explain(argparse.Namespace(unit=FIRST, at=None), inst) == 0
    out = capsys.readouterr().out
    assert DISPLAY in out
    assert UNIQUE not in out
    assert "@" not in out


def test_a_lost_claim_names_the_holder_by_display_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, host, _ = azure_board(tmp_path, monkeypatch)
    target = world.item_id(f"{CHANGE}:1")
    unit = covering(FIRST, (1,))
    real_claim = world.tracker.claim

    def taken_first(item_id: str) -> bool:
        host.edit(item_id, assigned_to=WIRE_IDENTITY)
        return real_claim(item_id)

    monkeypatch.setattr(world.tracker, "claim", taken_first)

    decision = start_decision(unit, changes_dir=world.changes_dir)

    assert decision.outcome == "skip"
    assert decision.items == (target,)
    assert DISPLAY in decision.reason
    assert "@" not in decision.reason
