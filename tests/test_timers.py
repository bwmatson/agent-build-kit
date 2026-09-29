"""Installing the systemd units on the machine that will run them.

The units carry an absolute `WorkingDirectory`, so they are only correct for
one checkout at one path. Rendering them into the planning repo at init time
baked in whoever ran init: a teammate cloning that repo got units pointing at
someone else's home directory, and `systemctl --user enable` accepted them.
These render on the machine doing the installing, against the installation it
is installing for.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit import timers


def fake_run(calls: list[list[str]]):
    def run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run


def test_the_units_are_rendered_against_the_installation_being_installed_for(
    tmp_path: Path,
) -> None:
    planning = tmp_path / "meta-agent"
    dest = tmp_path / "systemd-user"

    written, refused = timers.install(planning, dest=dest, run=fake_run([]))

    assert refused == []
    assert {path.name for path in written} == set(timers.UNITS)
    service = (dest / "abk-tick.service").read_text()
    assert f"WorkingDirectory={planning}" in service


def test_reinstalling_after_the_repo_moves_rewrites_the_path(tmp_path: Path) -> None:
    """The case the committed copies could not answer: the planning repo moved,
    so every unit points somewhere that is no longer an installation."""
    dest = tmp_path / "systemd-user"
    timers.install(tmp_path / "before", dest=dest, run=fake_run([]))

    timers.install(tmp_path / "after", dest=dest, run=fake_run([]))

    service = (dest / "abk-tick.service").read_text()
    assert f"WorkingDirectory={tmp_path / 'after'}" in service
    assert "before" not in service


def test_a_unit_this_framework_did_not_write_is_refused(tmp_path: Path) -> None:
    """Same guard as install-skills: a hand-written unit of the same name is
    someone's own work, and overwriting it silently would be the framework
    taking a file it does not own."""
    dest = tmp_path / "systemd-user"
    dest.mkdir()
    (dest / "abk-tick.service").write_text("[Service]\nExecStart=/usr/bin/true\n")

    written, refused = timers.install(tmp_path / "planning", dest=dest, run=fake_run([]))

    assert [path.name for path in refused] == ["abk-tick.service"]
    assert "abk-tick.service" not in {path.name for path in written}
    assert (dest / "abk-tick.service").read_text() == "[Service]\nExecStart=/usr/bin/true\n"


def test_installing_reloads_the_user_manager(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    timers.install(tmp_path / "planning", dest=tmp_path / "dest", run=fake_run(calls))

    assert calls == [["systemctl", "--user", "daemon-reload"]]


def test_enabling_starts_only_the_timers(tmp_path: Path) -> None:
    """Enabling a `.service` here would run a tick at boot outside its timer."""
    calls: list[list[str]] = []

    timers.install(tmp_path / "planning", dest=tmp_path / "dest", run=fake_run(calls), enable=True)

    assert calls[0] == ["systemctl", "--user", "daemon-reload"]
    enabled = [call for call in calls if "enable" in call]
    assert len(enabled) == 4
    assert all(call[-1].endswith(".timer") for call in enabled)


def test_a_dry_run_writes_nothing_and_runs_nothing(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    dest = tmp_path / "dest"

    written, refused = timers.install(
        tmp_path / "planning", dest=dest, run=fake_run(calls), dry_run=True
    )

    assert {path.name for path in written} == set(timers.UNITS)
    assert not dest.exists()
    assert calls == []


def test_the_installed_working_directory_is_readable(tmp_path: Path) -> None:
    """What doctor needs: which installation the units on this machine serve."""
    dest = tmp_path / "dest"
    timers.install(tmp_path / "planning", dest=dest, run=fake_run([]))

    assert timers.installed_root(dest) == tmp_path / "planning"


def test_no_installed_units_reads_as_none(tmp_path: Path) -> None:
    assert timers.installed_root(tmp_path / "empty") is None
