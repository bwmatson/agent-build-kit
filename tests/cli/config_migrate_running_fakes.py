"""What the tests of the running-units notice of `abk config --migrate` share: units in the unit
store beside the abk.yaml, and a terminal that keeps what the error stream held at each question."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.cli.config_migrate_fakes import Person
from tests.factories import stored_unit

ONE = (
    "abk: 1 unit is running (a-change/2). A write to abk.yaml or abk.local.yaml fails a build or "
    "track run in progress, so run this between ticks or when it has finished."
)


class Watching(Person):
    """A person who also keeps the error stream as it stood when each question was asked."""

    def __init__(self, capsys: pytest.CaptureFixture[str], *answers: str) -> None:
        super().__init__(capsys, None, *answers)
        self.err_when_asked: list[str] = []

    def readline(self, *_: object) -> str:
        answer = super().readline()
        self.err_when_asked.append(self.err)
        return answer


def running_unit(root: Path, uid: str = "a-change/2") -> None:
    """A unit in state `running` in the unit store beside the abk.yaml in `root`."""
    store = UnitStore(root / "runs" / "units.json")
    store.upsert([stored_unit(uid)])
    store.set_state(uid, RUNNING)


def run_watched(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
    *argv: str,
    answers: tuple[str, ...] = (),
) -> tuple[int, Watching]:
    """`abk config --migrate <argv>` with `answers` at the terminal: the exit code and the
    terminal."""
    terminal = Watching(capsys, *answers)
    monkeypatch.setattr(sys, "stdin", terminal)
    code = main(["--config", str(path), "config", "--migrate", *argv])
    terminal.collect()
    return code, terminal
