"""One tick over a repo in `processes` mode and another in `threads` mode runs each repo's units
by its own mode: the first repo's are marked and spawned as workers, the second's built in the
tick (spec: worker-kinds)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from tests.dispatcher_support import FakeSpawner, install_spawner
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


@pytest.fixture
def spawner(monkeypatch: pytest.MonkeyPatch) -> FakeSpawner:
    return install_spawner(monkeypatch)


def mixed(tmp_path: Path, *, top: str, app: str, platform: str) -> Installation:
    def repo(name: str, mode: str) -> dict[str, object]:
        return {
            "path": str(tmp_path / "checkouts" / name),
            "slug": f"example/{name}",
            "workers": {"mode": mode},
        }

    return workspace(
        tmp_path,
        workers={"mode": top},
        repos={"app": repo("app", app), "platform": repo("platform", platform)},
    )


def test_a_tick_spawns_the_processes_repos_units_and_builds_the_threads_repos_units(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = mixed(tmp_path, top="threads", app="processes", platform="threads")
    builder.store.upsert([stored("a/1"), stored("p/1", repo="platform")])

    assert tick(inst) == 0

    assert spawner.units == ["a/1"], "app's unit is a worker's to build"
    assert builder.started == ["p/1"], "platform's unit is built in the tick"
    assert builder.store.get("a/1").starting is not None
    assert builder.store.get("p/1").starting is None


def test_the_modes_swap_with_the_repos_and_the_top_level_value_does_not_decide(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = mixed(tmp_path, top="processes", app="threads", platform="processes")
    builder.store.upsert([stored("a/1"), stored("p/1", repo="platform")])

    assert tick(inst) == 0

    assert spawner.units == ["p/1"]
    assert builder.started == ["a/1"]


def test_a_processes_unit_that_becomes_ready_mid_pass_is_spawned_by_the_next_round(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = mixed(tmp_path, top="threads", app="processes", platform="threads")
    builder.store.upsert([stored("a/1"), stored("p/1", repo="platform")])
    # While p/1 builds, a/1's worker opens its PR and releases a/2.
    builder.scripts["p/1"] = lambda: builder.store.upsert([stored("a/2")])

    assert tick(inst) == 0

    assert spawner.units == ["a/1", "a/2"]
    assert builder.started == ["p/1"]
    assert builder.store.get("a/2").starting is not None
