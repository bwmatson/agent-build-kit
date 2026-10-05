"""The seam `build_unit` runs a unit through (docs/unit-graph.md).

Without a setting, the classic engine runs it; with `ABK_ENGINE=graph`, the
graph engine does, and the unit gets a thread named by its id.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import unit_engine
from agent_build_kit.pipeline.unit_engine import ClassicEngine, select_engine
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import CommitRejected
from agent_build_kit.settings import Settings, settings
from tests.conftest import make_installation
from tests.factories import stored_unit

UNIT = "feature/1"


class Rejected:
    """A runner that ends the unit, so what ran is visible on its record."""

    def __init__(self) -> None:
        self.ran: list[str] = []

    def run(self, unit, *, base, graph):
        self.ran.append(unit.id)
        raise CommitRejected("ruff...Failed")


def a_store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(UNIT, change="feature")])
    return store


def test_with_no_setting_the_engine_is_the_classic_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ABK_ENGINE", raising=False)

    engine = select_engine(Settings(_env_file=None).engine)

    assert isinstance(engine, ClassicEngine)


def test_abk_engine_graph_selects_the_graph_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABK_ENGINE", "graph")

    engine = select_engine(Settings(_env_file=None).engine)

    assert engine.name == "graph"


def test_the_classic_engine_builds_a_unit_through_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    store = a_store(tmp_path)
    runner = Rejected()
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: runner)

    ClassicEngine().build(inst, store.get(UNIT), store=store)

    assert runner.ran == [UNIT]
    assert store.get(UNIT).state == "failed"


def test_build_unit_with_no_setting_runs_the_classic_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    store = a_store(tmp_path)
    monkeypatch.setattr(settings, "engine", "classic")
    seen: list[str] = []

    def record(self, inst, unit, *, store) -> bool:
        seen.append(unit.id)
        return True

    monkeypatch.setattr(unit_engine.ClassicEngine, "build", record)

    assert cli.build_unit(inst, store.get(UNIT), store=store) is True

    assert seen == [UNIT]
    assert not (tmp_path / "unit-graphs.sqlite").exists(), "no thread for a classic build"


def test_an_unknown_engine_is_refused_when_settings_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABK_ENGINE", "grpah")

    with pytest.raises(ValidationError, match="(?i)engine"):
        Settings(_env_file=None)


def test_a_graph_build_that_errors_is_recorded_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    store = a_store(tmp_path)
    (inst.state_dir / "unit-graphs.sqlite").write_text("not a database")
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: Rejected())
    monkeypatch.setattr(settings, "engine", "graph")

    assert cli.build_unit(inst, store.get(UNIT), store=store) is True

    assert UNIT + ": failed" in capsys.readouterr().out
    assert store.get(UNIT).state == "failed"
