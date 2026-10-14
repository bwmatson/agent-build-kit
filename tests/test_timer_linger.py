"""The lingering check: without it the user manager, and every timer, stops
with the last login session."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from tests.conftest import make_installation
from tests.loginctl_fake import Loginctl, SubprocessModule

USER = "alice"
COMMAND = f"sudo loginctl enable-linger {USER}"


def test_linger_yes_is_on() -> None:
    assert timers.linger_state(USER, Loginctl("yes")) == "on"


def test_linger_no_is_off() -> None:
    runner = Loginctl("no")

    assert timers.linger_state(USER, runner) == "off"
    assert ["loginctl", "show-user", USER, "--property=Linger"] in runner.calls


def test_a_loginctl_that_fails_is_unknown() -> None:
    assert timers.linger_state(USER, Loginctl(None)) == "unknown"


def test_a_missing_loginctl_is_unknown() -> None:
    assert timers.linger_state(USER, Loginctl(missing=True)) == "unknown"


def test_enable_linger_reports_a_failure_as_false() -> None:
    assert timers.enable_linger(USER, Loginctl(enable_ok=False)) is False


def test_enable_linger_reports_success_and_never_waits_on_input() -> None:
    runner = Loginctl(enable_ok=True)

    assert timers.enable_linger(USER, runner) is True

    (kwargs,) = [
        k for c, k in zip(runner.calls, runner.kwargs, strict=True) if c[1] == "enable-linger"
    ]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs.get("timeout")


def test_enable_linger_without_loginctl_is_false() -> None:
    assert timers.enable_linger(USER, Loginctl(missing=True)) is False


# --- abk install-timers ------------------------------------------------------------


def planning(root: Path) -> Installation:
    inst = make_installation(root)
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    return inst


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A planning repo as the working directory, a unit directory of our own,
    and the user `alice`."""
    inst = planning(tmp_path)
    monkeypatch.chdir(inst.root)
    monkeypatch.setattr(timers, "user_unit_dir", lambda: tmp_path / "units")
    monkeypatch.setattr(timers, "current_user", lambda: USER)
    return inst.root


def use(monkeypatch: pytest.MonkeyPatch, runner: Loginctl) -> None:
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(runner))


def test_off_and_not_enableable_prints_the_command_and_why(
    machine: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    runner = Loginctl("no", enable_ok=False)
    use(monkeypatch, runner)

    code = main(["install-timers"])

    out = capsys.readouterr().out
    assert code == 0
    assert COMMAND in out
    assert "user manager" in out
    assert "login session" in out
    assert runner.tried_enable
    assert not runner.ran_sudo


def test_the_exit_status_is_what_it_was_without_the_advice(
    machine: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = Loginctl("no")
    use(monkeypatch, runner)
    units = machine.parent / "units"
    units.mkdir()
    (units / timers.unit_names(machine)[1]).write_text("[Unit]\nDescription=mine\n")

    assert main(["install-timers"]) == 1
    assert runner.asked


def test_off_and_enabled_by_the_command_says_so(
    machine: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    runner = Loginctl("no", enable_ok=True)
    use(monkeypatch, runner)

    code = main(["install-timers"])

    out = capsys.readouterr().out
    assert code == 0
    assert "linger" in out.lower()
    assert "enabled" in out
    assert "sudo loginctl" not in out
    assert not runner.ran_sudo


def test_lingering_already_on_says_nothing(
    machine: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    runner = Loginctl("yes")
    use(monkeypatch, runner)

    main(["install-timers"])

    assert runner.asked
    assert not runner.tried_enable
    assert "linger" not in capsys.readouterr().out.lower()


def test_no_loginctl_skips_the_check_silently(
    machine: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    runner = Loginctl(missing=True)
    use(monkeypatch, runner)

    code = main(["install-timers"])

    assert code == 0
    assert runner.asked
    assert not runner.tried_enable
    assert "linger" not in capsys.readouterr().out.lower()


def test_only_an_install_that_enables_checks(
    machine: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    runner = Loginctl("no")
    use(monkeypatch, runner)
    main(["install-timers"])
    assert runner.asked, "an ordinary install checks"

    for flags in (["--no-enable"], ["--dry-run"], ["--remove"]):
        other = Loginctl("no")
        use(monkeypatch, other)
        capsys.readouterr()
        main(["install-timers", *flags])
        assert not other.asked, flags
        assert "linger" not in capsys.readouterr().out.lower(), flags
