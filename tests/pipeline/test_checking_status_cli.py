"""`abk status` lists a checking unit apart from one awaiting review, and the
poll that records a pull request's checks keeps its state label in line."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.pipeline.pr_poller import PrState, state_path
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.fake_clock import FakeClock, install
from tests.forges.stand_in import StandInForge

PR = 7


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


def pull(*listed: tuple[str, CheckStatus]) -> PullRequest:
    return PullRequest(
        number=PR,
        head="spec/add-marker/1",
        base="main",
        state="open",
        checks=tuple(Check(name=name, status=status) for name, status in listed),
    )


def test_status_lists_a_checking_unit_apart_from_one_awaiting_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clock: FakeClock,
) -> None:
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("one/1", change="one"), stored_unit("two/1", change="two")])
    for uid, pr in (("one/1", 7), ("two/1", 8)):
        store.set_state(uid, IN_REVIEW, pr=pr)
        store.record_push(uid, "abc")
    clock.advance(3600)
    PrState.save(
        state_path(inst.state_dir, "app"),
        {"7": {"checks": {"CI": "pending"}}, "8": {"checks": {"CI": "passed"}}},
    )
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    lines = capsys.readouterr().out.splitlines()
    checking = next(line for line in lines if "one/1" in line)
    waiting = next(line for line in lines if "two/1" in line)
    assert "checking" in checking and "#7" in checking
    assert "awaiting review" not in checking
    assert "awaiting review" in waiting and "#8" in waiting
    assert "checking" not in waiting


def test_the_poll_moves_the_label_between_in_review_and_checking_without_a_state_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=PR)
    store.record_push("add-marker/1", "abc")
    clock.advance(3600)
    forge = StandInForge(prs=[pull(("CI", CheckStatus.PASSED))])
    forge.on_pr[PR] = {"in-review"}
    monkeypatch.setattr(inst, "forge_of", lambda repo: (forge, forge.repo_id()))

    def labels() -> set[str]:
        return forge.on_pr[PR] & {"in-review", "checking"}

    cli.poll_all(inst, store=store)
    assert labels() == {"in-review"}

    forge.prs = [pull(("CI", CheckStatus.PENDING))]
    cli.poll_all(inst, store=store)
    assert labels() == {"checking"}
    assert store.get("add-marker/1").state == "in_review"

    forge.prs = [pull(("CI", CheckStatus.PASSED))]
    cli.poll_all(inst, store=store)
    assert labels() == {"in-review"}
    assert store.get("add-marker/1").state == "in_review"
