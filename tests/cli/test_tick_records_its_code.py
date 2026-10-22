"""A real tick records the code it runs in `tick.json` before its first round
(spec: needs-can-wait-for-a-merge): its number, when it started, the kit checkout and its head."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import loaded_code
from agent_build_kit.pipeline.loaded_code import TICK_FILE
from tests.factories import git, init_repo
from tests.kit_checkout import kit_at
from tests.tick_driver import Setup, make_setup

pytestmark = pytest.mark.usefixtures("scripted_engine")

PREVIOUS = {
    "number": 4,
    "started_at": "2026-01-01T00:00:00Z",
    "kit_repo": None,
    "kit_root": None,
    "kit_head": None,
}


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    return make_setup(tmp_path, monkeypatch)


def record_path(setup: Setup) -> Path:
    return setup.inst.state_dir / TICK_FILE


def recorded(setup: Setup) -> dict[str, Any]:
    return json.loads(record_path(setup).read_text())


def test_a_tick_writes_its_record_before_the_first_round(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = kit_at(setup.inst.checkouts["app"], monkeypatch)
    record_path(setup).write_text(json.dumps(PREVIOUS))
    seen: list[dict[str, Any]] = []
    real = cli.run_round

    def round_(*args: Any, **kwargs: Any):
        seen.append(recorded(setup))
        return real(*args, **kwargs)

    monkeypatch.setattr(cli, "run_round", round_)

    setup.tick()

    (first, *_) = seen
    assert first["number"] == 5
    assert first["kit_head"] == head
    assert first["kit_root"] == str(setup.inst.checkouts["app"].resolve())
    assert first["kit_repo"] == "app"
    assert first["started_at"] != PREVIOUS["started_at"]
    assert sorted(p.name for p in record_path(setup).parent.glob("tick.json*")) == [TICK_FILE]


def test_the_first_tick_is_number_one(setup: Setup, monkeypatch: pytest.MonkeyPatch) -> None:
    kit_at(setup.inst.checkouts["app"], monkeypatch)

    setup.tick()

    assert recorded(setup)["number"] == 1


def test_a_dry_run_writes_nothing_and_leaves_the_last_record(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit_at(setup.inst.checkouts["app"], monkeypatch)

    setup.dry_tick()
    assert not record_path(setup).exists()

    record_path(setup).write_text(json.dumps(PREVIOUS))
    setup.dry_tick()
    assert recorded(setup) == PREVIOUS

    setup.tick()
    assert recorded(setup)["number"] == 5, "the next real tick numbers from the last record"


def test_an_unreadable_checkout_writes_a_null_head(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A work tree with no commit has no head to read."""
    kit_at(setup.inst.checkouts["app"], monkeypatch, commits=False)

    setup.tick()

    assert recorded(setup)["kit_head"] is None


def test_a_package_outside_any_work_tree_records_no_checkout(
    setup: Setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = tmp_path / "site-packages" / "pkg"
    installed.mkdir(parents=True)
    monkeypatch.setattr(loaded_code, "PACKAGE_DIR", installed)

    setup.tick()

    assert recorded(setup)["kit_head"] is None
    assert recorded(setup)["kit_repo"] is None


def test_the_kits_repository_is_the_configured_repo_whose_path_is_the_work_tree(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit_at(setup.inst.checkouts["platform"], monkeypatch)

    setup.tick()

    assert recorded(setup)["kit_repo"] == "platform"


def test_no_repo_is_the_kits_when_no_configured_path_is_the_work_tree(
    setup: Setup, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "elsewhere"
    head = kit_at(other, monkeypatch)
    init_repo(setup.inst.checkouts["app"])

    setup.tick()

    assert recorded(setup)["kit_repo"] is None
    assert recorded(setup)["kit_root"] == str(other.resolve())
    assert recorded(setup)["kit_head"] == head == git(other, "rev-parse", "HEAD")
