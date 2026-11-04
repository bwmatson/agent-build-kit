"""`abk doctor` checks the transient-unit path a worker needs: lingering, `systemd-run` and the
wake path unit, in `processes` mode only (spec: unit-workers)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.test_doctor import Answers
from tests.factories import planning, which_all
from tests.loginctl_fake import Loginctl, SubprocessModule

NAME = "workers"


class Machine:
    """A runner answering `loginctl` as `linger` says and every other command as `Answers` does."""

    def __init__(self, linger: str) -> None:
        self.loginctl = Loginctl(linger)
        self.answers = Answers()

    def __call__(self, argv, **kwargs):
        if argv[0] == "loginctl":
            return self.loginctl(argv, **kwargs)
        return self.answers(argv, **kwargs)


def without_systemd_run(name: str) -> str | None:
    return None if name == "systemd-run" else which_all(name)


@pytest.fixture
def units(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dest = tmp_path / "units"
    monkeypatch.setattr(timers, "user_unit_dir", lambda: dest)
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(Loginctl("yes")))
    return dest


def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> Path:
    inst = planning(tmp_path)
    config = inst.root / "abk.yaml"
    config.write_text(config.read_text() + f"workers:\n  mode: {mode}\n")
    monkeypatch.chdir(inst.root)
    return config


def workers_checks(
    config: Path,
    units: Path,
    *,
    linger: str = "yes",
    which: Callable[[str], str | None] = which_all,
) -> list[Check]:
    checks = run_doctor(config, run=Machine(linger), which=which, units=units)
    return [check for check in checks if check.name == NAME]


def test_processes_mode_with_the_whole_path_has_no_complaint(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configured(tmp_path, monkeypatch, "processes")
    assert main(["install-timers"]) == 0

    checks = workers_checks(config, units)

    assert checks
    assert {check.status for check in checks} == {"ok"}


def test_a_missing_wake_unit_says_to_install_the_timers(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configured(tmp_path, monkeypatch, "processes")
    units.mkdir()

    checks = workers_checks(config, units)

    [problem] = [check for check in checks if check.status != "ok"]
    assert "wake" in problem.detail
    assert "abk install-timers" in problem.fix


def test_lingering_off_says_to_enable_it(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configured(tmp_path, monkeypatch, "processes")
    assert main(["install-timers"]) == 0

    machine = Machine("no")

    checks = run_doctor(config, run=machine, which=which_all, units=units)

    # Lingering is asked once and warned about once, though the timers and the workers both need it.
    [problem] = [c for c in checks if c.status != "ok" and "lingering is off" in c.detail]
    assert "loginctl enable-linger" in problem.fix
    assert len([argv for argv in machine.loginctl.calls if "show-user" in argv]) == 1
    assert {c.status for c in checks if c.name == NAME} == {"ok"}


def test_a_wake_unit_missing_from_installed_timers_is_reported_once(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configured(tmp_path, monkeypatch, "processes")
    assert main(["install-timers"]) == 0
    next(units.glob("*-wake.path")).unlink()

    checks = run_doctor(config, run=Machine("yes"), which=which_all, units=units)

    named = [c for c in checks if c.status != "ok" and "wake.path" in c.detail]
    assert len(named) == 1


def test_a_machine_without_systemd_run_says_what_to_install(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configured(tmp_path, monkeypatch, "processes")
    assert main(["install-timers"]) == 0

    checks = workers_checks(config, units, which=without_systemd_run)

    [problem] = [check for check in checks if check.status != "ok"]
    assert "systemd-run" in problem.detail
    assert "systemd" in problem.fix


def test_threads_mode_makes_no_complaint_about_the_path(
    tmp_path: Path, units: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = configured(tmp_path, monkeypatch, "threads")
    units.mkdir()

    checks = workers_checks(config, units, linger="no", which=without_systemd_run)

    # The mode is reported, and nothing about the path is asked of it.
    assert checks
    assert not [check for check in checks if check.status in ("warn", "fail")]
