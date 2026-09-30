"""`abk install-timers`: the systemd units for this machine, this installation.

The units carry an absolute `WorkingDirectory`, so they are correct for exactly
one checkout at one path. That is why they are rendered on the machine doing the
installing rather than committed — see `timers.py` — and why this command
exists at all: without it the units sit in the planning repo as files nothing
reads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from tests.conftest import make_installation


def planning(root: Path) -> Installation:
    """An installation the CLI can find: in memory is not enough, since the
    command resolves abk.yaml from the working directory upwards."""
    inst = make_installation(root)
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    return inst


@pytest.fixture
def units(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A unit directory of our own, so a test never writes to the real one."""
    dest = tmp_path / "units"
    monkeypatch.setattr(timers, "user_unit_dir", lambda: dest)
    return dest


def test_the_units_land_pointing_at_this_installation(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The failure this replaces: units rendered at init time named whoever ran
    init, so everyone who cloned the repo afterwards got units aimed at someone
    else's home directory."""
    inst = planning(tmp_path)
    monkeypatch.chdir(inst.root)
    calls: list[list[str]] = []
    monkeypatch.setattr(timers, "subprocess", _Recorder(calls))

    code = main(["install-timers"])

    assert code == 0
    assert timers.installed_root(units) == inst.root.resolve()
    assert sorted(p.name for p in units.iterdir()) == sorted(timers.UNITS)
    assert "wrote" in capsys.readouterr().out


def test_a_dry_run_writes_nothing(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inst = planning(tmp_path)
    monkeypatch.chdir(inst.root)

    code = main(["install-timers", "--dry-run"])

    assert code == 0
    assert not units.exists()
    assert "would write" in capsys.readouterr().out


def test_a_unit_somebody_else_wrote_is_refused(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A file without the marker is somebody's own work, and overwriting it is
    the one thing an install must not do."""
    inst = planning(tmp_path)
    monkeypatch.chdir(inst.root)
    units.mkdir(parents=True)
    mine = units / "abk-tick.timer"
    mine.write_text("[Unit]\nDescription=mine\n")
    monkeypatch.setattr(timers, "subprocess", _Recorder([]))

    code = main(["install-timers"])

    assert code == 1
    assert mine.read_text() == "[Unit]\nDescription=mine\n"
    assert "refused" in capsys.readouterr().out
    assert (units / "abk-tick.service").exists(), "the rest still land"


def test_enable_starts_the_timers_and_not_the_services(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enabling a `.service` would run it at boot, outside the schedule that is
    the whole point of the timer beside it."""
    inst = planning(tmp_path)
    monkeypatch.chdir(inst.root)
    calls: list[list[str]] = []
    monkeypatch.setattr(timers, "subprocess", _Recorder(calls))

    code = main(["install-timers", "--enable"])

    assert code == 0
    enabled = [c[-1] for c in calls if "enable" in c]
    assert enabled == [name for name in timers.UNITS if name.endswith(".timer")]
    assert not any(name.endswith(".service") for name in enabled)
    assert ["systemctl", "--user", "daemon-reload"] in calls


def test_without_an_installation_it_says_so(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The units name a planning repo; there is nothing to render without one."""
    monkeypatch.chdir(tmp_path)

    code = main(["install-timers"])

    assert code == 2
    assert "abk.yaml" in capsys.readouterr().err


class _Recorder:
    """Stands in for the `subprocess` module `timers` reaches systemctl through."""

    def __init__(self, calls: list[list[str]]) -> None:
        self.calls = calls

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))

        class Done:
            returncode = 0
            stdout = ""
            stderr = ""

        return Done()
