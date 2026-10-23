"""A landing says so on the pull request: a comment and a label (spec: auto-land)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import MERGED
from tests.forges.stand_in import StandInForge
from tests.landing_support import PR, UNIT, landing, make_landable

LABEL = "auto-landed"
# The reason `tests.verdict_fakes` gives each verdict it writes, and the class `make_landable` sets.
REASON = "because"
UNIT_CLASS = "docs"


class RefusedComment(StandInForge):
    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        raise RuntimeError("403 comments are closed")


def test_a_landing_comments_with_the_class_and_the_verdict_s_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)

    landed.land()

    [comment] = landed.forge.comments
    assert "without a person" in comment
    assert UNIT_CLASS in comment
    assert REASON in comment


def test_a_landing_adds_the_label_auto_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)

    landed.land()

    assert LABEL in landed.forge.on_pr[PR]


def test_a_comment_the_host_refuses_is_logged_and_leaves_the_record_and_the_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch, RefusedComment())

    landed.land()

    unit = landed.store.get(UNIT)
    assert (unit.state, unit.cause) == (MERGED, Cause.AUTO_LANDED)
    assert not landed.intent()
    assert any("comments are closed" in line for line in landed.logged)
    assert LABEL in landed.forge.on_pr[PR]


def test_a_label_the_host_refuses_is_logged_and_leaves_the_record_and_the_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch, StandInForge(label_errors=("add", "set")))

    landed.land()

    unit = landed.store.get(UNIT)
    assert (unit.state, unit.cause) == (MERGED, Cause.AUTO_LANDED)
    assert not landed.intent()
    assert any("403" in line for line in landed.logged)
    assert len(landed.forge.comments) == 1


def test_a_unit_that_did_not_land_gets_neither_comment_nor_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)
    make_landable(landed.inst, landed.store, landed.forge, {"c/9": 9})
    landed.forge.on_pr[9] = {HOLD_LABEL}

    landed.land()

    assert LABEL in landed.forge.on_pr[PR], "the unit that landed is told apart from the held one"
    assert landed.forge.on_pr[9] == {HOLD_LABEL}
    assert len(landed.forge.comments) == 1
    assert [call for call in landed.forge.calls if call == ("comment", 9)] == []
