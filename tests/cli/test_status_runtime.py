"""`abk status` is what an operator runs to find out what is wrong, so a runtime
that is selected but not installed is something it reports, not dies on."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED
from agent_build_kit.settings import reload
from tests.conftest import make_installation
from tests.factories import unit


@pytest.fixture
def machine_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ABK_RUNTIME", "not-installed")
    reload(None)
    yield
    monkeypatch.delenv("ABK_RUNTIME", raising=False)
    reload(None)


def test_status_reports_a_runtime_that_is_not_available_and_carries_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], machine_runtime: None
) -> None:
    code = cli.cmd_status(argparse.Namespace(), make_installation(tmp_path))

    assert code == 0
    output = capsys.readouterr()
    assert "runtime not-installed is not available" in output.out + output.err
    assert "no units planned" in output.out + output.err


def test_status_lists_the_units_in_flight_that_carry_no_cause(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], machine_runtime: None
) -> None:
    """The ones a store from before causes holds, to requeue or hold again once by hand."""
    store = cli.store_for(make_installation(tmp_path))
    store.upsert([unit("a/1"), unit("a/2"), unit("a/3"), unit("a/4")])
    store.set_state("a/1", HELD, note="held by a reviewer")
    store.set_state("a/2", PLANNED, note="rework requested: x", branch="spec/a/2")
    store.set_state("a/3", PLANNED, note="requeued", cause=Cause.REQUEUED, branch="spec/a/3")
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), make_installation(tmp_path))

    output = capsys.readouterr()
    text = output.out + output.err
    assert "no recorded cause: a/1, a/2" in text
    assert "a/3" not in text.split("no recorded cause")[1]


def test_status_does_not_list_a_unit_held_by_the_label_as_lacking_a_cause(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], machine_runtime: None
) -> None:
    store = cli.store_for(make_installation(tmp_path))
    store.upsert([unit("a/1")])
    store.set_state("a/1", IN_REVIEW, pr=1, branch="spec/a/1")
    events.on_hold(1, repo="app", store=store, log=lambda m: None)
    assert store.get("a/1").state == HELD
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), make_installation(tmp_path))

    output = capsys.readouterr()
    assert "no recorded cause" not in output.out + output.err
