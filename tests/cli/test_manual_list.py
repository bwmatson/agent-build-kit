"""`abk manual list` (spec: manual-steps): the one list of steps a person has to do.

The command runs through the real command line over a store written with stored steps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, ManualStep
from tests.conftest import make_installation
from tests.factories import unit

CHECKED = datetime(2026, 10, 11, 9, 30, tzinfo=UTC)


def step(slug: str, **kw: object) -> ManualStep:
    return ManualStep(
        slug=slug,
        text=f"A person does {slug}",
        runbook=f"docs/runbook-x.md#{slug}",
        check=f".abk/manual/{slug}.sh",
        **kw,  # type: ignore[arg-type]
    )


class Listing:
    def __init__(self, tmp_path: Path) -> None:
        installation = make_installation(tmp_path / "planning")
        self.config = installation.root / "abk.yaml"
        self.config.write_text(dump(installation.config))
        self.store = UnitStore(installation.state_dir / "units.json")

    def waiting(self, uid: str, *steps: ManualStep) -> None:
        self.store.upsert([unit(uid)])
        self.store.set_manual_steps(uid, steps)
        self.store.set_state(uid, PLANNED)

    def run(self, capsys: pytest.CaptureFixture[str], *flags: str) -> str:
        capsys.readouterr()
        assert main(["--config", str(self.config), "manual", "list", *flags]) == 0
        return capsys.readouterr().out


@pytest.fixture
def listing(tmp_path: Path) -> Listing:
    return Listing(tmp_path)


def test_every_outstanding_step_is_listed_with_its_unit_runbook_and_last_result(
    listing: Listing, capsys: pytest.CaptureFixture[str]
) -> None:
    listing.waiting(
        "feature/1",
        step("flip", outcome="unmet", last_line="marker still off", checked_at=CHECKED),
    )
    listing.waiting("platform/2", step("enable", outcome="failed", last_line="exited 2"))

    out = listing.run(capsys)

    for expected in (
        "feature/1",
        "flip",
        "A person does flip",
        "docs/runbook-x.md#flip",
        "marker still off",
        "2026-10-11",
        "platform/2",
        "enable",
        "A person does enable",
        "docs/runbook-x.md#enable",
        "exited 2",
    ):
        assert expected in out, out


def test_a_done_step_is_left_out_unless_done_is_asked_for(
    listing: Listing, capsys: pytest.CaptureFixture[str]
) -> None:
    listing.waiting(
        "feature/1",
        step("finished", done=True, outcome="met", last_line="all set"),
        step("pending", outcome="unmet", last_line="not yet"),
    )

    plain = listing.run(capsys)
    with_done = listing.run(capsys, "--done")

    assert "pending" in plain and "finished" not in plain
    assert "finished" in with_done and "all set" in with_done


def test_with_nothing_outstanding_the_list_says_so(
    listing: Listing, capsys: pytest.CaptureFixture[str]
) -> None:
    listing.waiting("feature/1", step("finished", done=True, outcome="met"))

    out = listing.run(capsys)

    assert "no manual steps outstanding" in out.lower()
    assert "finished" not in out
