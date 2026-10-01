"""The production wiring of a unit's state labels: that the store `abk` builds
writes them where state changes, and that the poll `abk` runs takes a rework
instruction off once it has acted on it. Both go through the real `cli`
functions, with only the code host replaced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges import PullRequest
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.vocabulary import change_label
from tests.conftest import make_installation
from tests.factories import stored_unit as unit
from tests.forges.stand_in import StandInForge

PR = 7
UNIT = "add-marker/1"


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning")


@pytest.fixture
def forge(inst: Installation, monkeypatch: pytest.MonkeyPatch) -> StandInForge:
    """The host `app` is on; every other repo is on a host with nothing open."""
    app = StandInForge(prs=[PullRequest(number=PR, head=f"spec/{UNIT}", base="main", state="open")])
    elsewhere = StandInForge()

    def forge_of(name: str):
        host = app if name == "app" else elsewhere
        return host, host.repo_id()

    monkeypatch.setattr(inst, "forge_of", forge_of)
    return app


def test_the_store_the_cli_builds_labels_a_pull_request_as_its_unit_changes(
    inst: Installation, forge: StandInForge
) -> None:
    store = cli.store_for(inst)
    store.upsert([unit(UNIT)])

    store.set_state(UNIT, IN_REVIEW, pr=PR, branch=f"spec/{UNIT}")

    assert {"in-review", change_label("add-marker").name} <= forge.on_pr[PR]


def test_the_poll_the_cli_runs_takes_a_rework_label_off_once_it_has_acted(
    inst: Installation, forge: StandInForge
) -> None:
    store = cli.store_for(inst)
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, IN_REVIEW, pr=PR, branch=f"spec/{UNIT}")
    cli.poll_all(inst, store=store)  # the first poll records, and dispatches nothing
    assert store.get(UNIT).state == IN_REVIEW
    forge.on_pr[PR].add("agent-rework")

    cli.poll_all(inst, store=store)

    assert store.get(UNIT).state == PLANNED
    assert "agent-rework" not in forge.on_pr[PR]
