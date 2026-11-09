"""A pass hands units to workers through admission: each carries its worker's `starting` marker
until its build takes the branch lock, which then holds its place; a unit admission refuses is not
started."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def test_a_unit_admission_refuses_is_not_started(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = workspace(tmp_path)
    builder.store.upsert([stored("feature/1")])
    monkeypatch.setattr(cli, "admit", lambda *args, **kwargs: [])

    assert tick(inst) == 0

    assert builder.started == []
    assert UnitStore(tmp_path / "units.json").get("feature/1").starting is None
