"""The production wiring of a unit's state labels: that the store `abk` builds
writes them where state changes, and that the poll `abk` runs takes a rework
instruction off once it has acted on it. Both go through the real `cli`
functions, with only the code host replaced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges import PullRequest
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS
from agent_build_kit.pipeline.vocabulary import change_label, review_label_names
from tests.conftest import make_installation
from tests.factories import activate_with
from tests.factories import stored_unit as unit
from tests.forges.stand_in import StandInForge
from tests.verdict_fakes import write_verdicts

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
    # The rework handler reads the reviewer's words through the active
    # workspace's forge, not the installation's: left alone it asked the real
    # host for pull request 7 of `example/app`.
    monkeypatch.setattr(
        forges,
        "for_repo",
        lambda name: (
            (app if name == "app" else elsewhere),
            (app if name == "app" else elsewhere).repo_id(),
        ),
    )
    return app


def test_the_store_the_cli_builds_labels_a_pull_request_as_its_unit_changes(
    inst: Installation, forge: StandInForge
) -> None:
    store = cli.store_for(inst)
    store.upsert([unit(UNIT)])

    store.set_state(UNIT, IN_REVIEW, pr=PR, branch=f"spec/{UNIT}")

    assert {"in-review", change_label("add-marker").name} <= forge.on_pr[PR]


def test_the_store_the_cli_builds_puts_the_review_label_of_the_recorded_verdict_on_the_pull_request(
    inst: Installation, forge: StandInForge
) -> None:
    activate_with(review={"enabled": True})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    write_verdicts(inst.state_dir / VERDICTS, {UNIT: ReviewTier.LIGHT})
    store = cli.store_for(inst)
    store.upsert([unit(UNIT)])

    store.set_state(UNIT, IN_REVIEW, pr=PR, branch=f"spec/{UNIT}")
    assert forge.on_pr[PR] & review_label_names() == {"review-light"}

    write_verdicts(inst.state_dir / VERDICTS, {UNIT: ReviewTier.FULL})
    store.set_state(UNIT, IN_REVIEW)
    assert forge.on_pr[PR] & review_label_names() == {"review-full"}


def test_the_store_the_cli_builds_makes_a_pull_request_a_draft_while_its_unit_runs(
    inst: Installation, forge: StandInForge
) -> None:
    store = cli.store_for(inst)
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, IN_REVIEW, pr=PR, branch=f"spec/{UNIT}")

    store.set_state(UNIT, RUNNING)
    assert forge.is_draft[PR] is True

    store.set_state(UNIT, IN_REVIEW)
    assert forge.is_draft[PR] is False
    # Both writers hang off the one hook.
    assert "in-review" in forge.on_pr[PR]


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


def test_the_poll_the_cli_runs_stamps_the_unit_whose_pull_request_a_person_answered(
    inst: Installation, forge: StandInForge
) -> None:
    store = cli.store_for(inst)
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, IN_REVIEW, pr=PR, branch=f"spec/{UNIT}")
    cli.poll_all(inst, store=store)
    assert store.get(UNIT).first_human_activity_at is None

    forge.prs[0] = PullRequest(
        number=PR,
        head=f"spec/{UNIT}",
        base="main",
        state="open",
        conversation=("c1",),
        comment_bodies=("looks odd",),
    )
    cli.poll_all(inst, store=store)

    assert store.get(UNIT).first_human_activity_at is not None
