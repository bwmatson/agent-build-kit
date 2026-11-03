"""`abk install-timers` and the wake path: a path unit watching `runs/wake` whose service starts
the tick, installed with the other units and taken off with them."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.cli import main
from agent_build_kit.pipeline.snapshots import WAKE
from tests.factories import planning
from tests.loginctl_fake import Loginctl, SubprocessModule


@pytest.fixture
def units(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dest = tmp_path / "units"
    monkeypatch.setattr(timers, "user_unit_dir", lambda: dest)
    return dest


def named(units: Path, suffix: str) -> Path:
    [found] = [path for path in units.iterdir() if path.name.endswith(suffix)]
    return found


def test_a_path_unit_watches_the_wake_file(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = planning(tmp_path)
    monkeypatch.chdir(inst.root)
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(Loginctl("yes")))

    assert main(["install-timers"]) == 0

    path_unit = named(units, "-wake.path")
    assert f"PathChanged={inst.state_dir / WAKE}" in path_unit.read_text()
    assert timers.MARKER in path_unit.read_text()


def test_the_wake_service_starts_the_tick(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = planning(tmp_path)
    monkeypatch.chdir(inst.root)
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(Loginctl("yes")))

    main(["install-timers"])

    tick = named(units, "-tick.service").name
    assert tick in named(units, "-wake.service").read_text()
    assert sorted(path.name for path in units.iterdir()) == sorted(timers.unit_names(inst.root))


def test_the_path_unit_is_enabled_with_the_timers(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = planning(tmp_path)
    monkeypatch.chdir(inst.root)
    calls: list[list[str]] = []
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(Loginctl("yes", calls=calls)))

    main(["install-timers"])

    enabled = [argv[-1] for argv in calls if "enable" in argv]
    assert any(name.endswith("-wake.path") for name in enabled)


def test_removing_takes_the_path_unit_and_its_service_off(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = planning(tmp_path)
    monkeypatch.chdir(inst.root)
    calls: list[list[str]] = []
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(Loginctl("yes", calls=calls)))
    main(["install-timers"])
    wake_path = named(units, "-wake.path").name

    assert main(["install-timers", "--remove"]) == 0

    assert not units.exists() or not list(units.iterdir())
    assert any("disable" in argv and wake_path in argv for argv in calls)
