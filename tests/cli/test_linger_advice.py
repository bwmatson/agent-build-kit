"""`abk init` and `abk doctor` say what `abk install-timers` says about lingering."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import dump
from tests.cli.init_quiet import quiet
from tests.conftest import make_installation
from tests.factories import git, init_repo, recognised_planning
from tests.loginctl_fake import Loginctl, SubprocessModule

USER = "alice"


@pytest.fixture(autouse=True)
def alice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timers, "current_user", lambda: USER)


def which_all(name: str) -> str | None:
    return f"/usr/bin/{name}"


# --- abk init ----------------------------------------------------------------------


def init_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: Loginctl, capsys) -> str:
    quiet(monkeypatch)
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "t")
        monkeypatch.setenv(f"{key}_EMAIL", "t@t.t")
    monkeypatch.setattr(timers, "subprocess", SubprocessModule(runner))
    app = init_repo(tmp_path / "app")
    git(app, "remote", "add", "origin", "git@github.com:example/app.git")
    planning = recognised_planning(tmp_path / "planning")
    main(["init", str(planning), "--repo", str(app), "--yes", "--skip-research", "--skip-propose"])
    return capsys.readouterr().out


def test_init_carries_the_advice_when_lingering_is_off_and_not_otherwise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    off = init_output(tmp_path / "off", monkeypatch, Loginctl("no"), capsys)
    on = init_output(tmp_path / "on", monkeypatch, Loginctl("yes"), capsys)

    assert timers.linger_advice(USER) in off
    assert "linger" not in on.lower()
    assert "Next steps" in on


# --- abk doctor --------------------------------------------------------------------


def linger_check(tmp_path: Path, runner: Loginctl, *, installed: bool = True) -> Check | None:
    inst = make_installation(tmp_path)
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    units = tmp_path / "units"
    if installed:
        timers.install(inst.root, dest=units, run=Loginctl())
    checks = run_doctor(inst.root / "abk.yaml", run=runner, which=which_all, units=units)
    return next((c for c in checks if c.name == "linger"), None)


def test_doctor_warns_naming_the_command_when_timers_run_without_lingering(
    tmp_path: Path,
) -> None:
    check = linger_check(tmp_path, Loginctl("no"))

    assert check is not None
    assert check.status == "warn"
    assert timers.linger_advice(USER) in check.fix
    assert f"sudo loginctl enable-linger {USER}" in check.fix


def test_doctor_reports_nothing_when_there_is_nothing_to_warn_about(tmp_path: Path) -> None:
    assert linger_check(tmp_path / "warns", Loginctl("no")) is not None, "the control"

    assert linger_check(tmp_path / "on", Loginctl("yes")) is None
    assert linger_check(tmp_path / "none", Loginctl("no"), installed=False) is None
    assert linger_check(tmp_path / "unknown", Loginctl(None)) is None
    assert linger_check(tmp_path / "missing", Loginctl(missing=True)) is None
