"""A tick or a status in a process with the usage guard off says so, and takes no reading.

The line is the first one the tick prints and one `abk status` shows. With the guard on,
neither command mentions it.
"""

from __future__ import annotations

import re

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.settings import settings
from tests.pipeline import test_cli_pipeline as base
from tests.pipeline.test_cli_pipeline import (  # noqa: F401 — fixtures
    FakeRunner,
    argv_namespace,
    healthy,
    isolated,
    stored,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")

LINE = "usage guard off (ABK_USAGE_GUARD) — no usage is read and no start is held for usage"


class Readings:
    """`current_usage` in place of the real one: it counts the readings asked for."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.taken = 0
        original = cli.current_usage

        def counted():  # noqa: ANN202
            self.taken += 1
            return original()

        monkeypatch.setattr(cli, "current_usage", counted)


def lines(out: str) -> list[str]:
    """The printed lines without their time stamps."""
    return [re.sub(r"^\[[\d:]+\] ", "", line) for line in out.splitlines() if line.strip()]


def tick(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: FakeRunner(built))
    assert cli.cmd_tick(argv_namespace(dry_run=False), base.inst) == 0


def test_a_tick_says_the_guard_is_off_first_only_when_it_is_and_then_reads_nothing(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    UnitStore(base.inst.state_dir / "units.json").upsert([stored(), stored("add-marker/2")])
    monkeypatch.setattr(settings, "usage_guard", "on")
    tick(monkeypatch)
    assert "ABK_USAGE_GUARD" not in capsys.readouterr().out

    monkeypatch.setattr(settings, "usage_guard", "off")
    readings = Readings(monkeypatch)
    tick(monkeypatch)

    assert lines(capsys.readouterr().out)[0] == LINE
    assert readings.taken == 0
    assert not (base.inst.state_dir / "paused.json").exists()


def test_the_status_shows_the_line_only_when_the_guard_is_off(
    isolated,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = build_parser().parse_args(["status"])
    monkeypatch.setattr(settings, "usage_guard", "on")
    assert cli.cmd_status(status, base.inst) == 0
    assert "ABK_USAGE_GUARD" not in capsys.readouterr().out

    monkeypatch.setattr(settings, "usage_guard", "off")
    assert cli.cmd_status(status, base.inst) == 0

    assert LINE in lines(capsys.readouterr().out)
