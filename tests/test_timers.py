"""Installing the systemd units on the machine that will run them.

The units carry an absolute `WorkingDirectory`, so they are only correct for
one checkout at one path. Rendering them into the planning repo at init time
baked in whoever ran init: a teammate cloning that repo got units pointing at
someone else's home directory, and `systemctl --user enable` accepted them.
These render on the machine doing the installing, against the installation it
is installing for.

The other thing one machine has to survive is *several* installations. The
user manager has one namespace, so units named for the framework rather than
for the installation would have the second install quietly replace the first's
— both stamped with the same marker, so nothing would refuse it, and the first
workspace would simply stop being ticked.
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


def planning_at(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return root


# --- one installation ---------------------------------------------------------------


def test_the_units_are_rendered_against_the_installation_being_installed_for(
    tmp_path: Path,
) -> None:
    planning = planning_at(tmp_path, "meta-agent")
    dest = tmp_path / "units"

    change = timers.install(planning, dest=dest, run=fake_run([]))

    assert {path.name for path in change.written} == set(timers.unit_names(planning))
    assert timers.installed_root(dest, planning) == planning.resolve()
    assert (
        f"WorkingDirectory={planning.resolve()}"
        in (dest / timers.unit_names(planning)[0]).read_text()
    )


def test_every_unit_is_named_for_its_installation(tmp_path: Path) -> None:
    """The name is what keeps two workspaces apart in one user manager."""
    planning = planning_at(tmp_path, "meta-agent")

    names = timers.unit_names(planning)

    assert all("meta-agent" in name for name in names)
    assert sorted(names) == sorted([f"abk-meta-agent-{base}" for base in timers.BASE_UNITS])


def test_a_name_systemd_would_refuse_is_made_safe(tmp_path: Path) -> None:
    """A checkout directory may be called anything at all; a unit name may not."""
    planning = planning_at(tmp_path, "AI%20Accelerators meta")

    names = timers.unit_names(planning)

    assert all(set(name) <= set(timers.SAFE_CHARACTERS) for name in names), names
    assert "abk-AI-20Accelerators-meta-tick.service" in names


# --- several installations ----------------------------------------------------------


def test_a_second_installation_does_not_displace_the_first(tmp_path: Path) -> None:
    """The failure this prevents: the first workspace silently stops ticking."""
    first = planning_at(tmp_path, "one")
    second = planning_at(tmp_path, "two")
    dest = tmp_path / "units"

    timers.install(first, dest=dest, run=fake_run([]))
    timers.install(second, dest=dest, run=fake_run([]))

    assert timers.installed_root(dest, first) == first.resolve()
    assert timers.installed_root(dest, second) == second.resolve()
    assert len(list(dest.iterdir())) == 2 * len(timers.BASE_UNITS)


def test_removing_one_installation_leaves_the_other_running(tmp_path: Path) -> None:
    first = planning_at(tmp_path, "one")
    second = planning_at(tmp_path, "two")
    dest = tmp_path / "units"
    timers.install(first, dest=dest, run=fake_run([]))
    timers.install(second, dest=dest, run=fake_run([]))

    change = timers.remove(first, dest=dest, run=fake_run([]))

    assert {path.name for path in change.removed} == set(timers.unit_names(first))
    assert timers.installed_root(dest, first) is None
    assert timers.installed_root(dest, second) == second.resolve()


# --- running it twice ---------------------------------------------------------------


def test_installing_what_is_already_there_changes_nothing(tmp_path: Path) -> None:
    """Idempotent: the command is safe to run from a setup script, and says
    plainly that it did nothing rather than reporting eight writes."""
    planning = planning_at(tmp_path, "meta-agent")
    dest = tmp_path / "units"
    timers.install(planning, dest=dest, run=fake_run([]))
    stamps = {p.name: p.stat().st_mtime_ns for p in dest.iterdir()}
    calls: list[list[str]] = []

    change = timers.install(planning, dest=dest, run=fake_run(calls))

    assert change.written == ()
    assert {path.name for path in change.unchanged} == set(timers.unit_names(planning))
    assert {p.name: p.stat().st_mtime_ns for p in dest.iterdir()} == stamps
    assert ["systemctl", "--user", "daemon-reload"] not in calls, (
        "nothing changed, so the manager is not asked to reload"
    )


def test_a_unit_whose_content_moved_on_is_rewritten(tmp_path: Path) -> None:
    """Reinstalling is the repair when the framework's template changes."""
    planning = planning_at(tmp_path, "meta-agent")
    dest = tmp_path / "units"
    timers.install(planning, dest=dest, run=fake_run([]))
    target = dest / timers.unit_names(planning)[0]
    target.write_text(f"{timers.MARKER}\nstale\n")
    calls: list[list[str]] = []

    change = timers.install(planning, dest=dest, run=fake_run(calls))

    assert [path.name for path in change.written] == [target.name]
    assert "stale" not in target.read_text()
    assert ["systemctl", "--user", "daemon-reload"] in calls


def test_a_unit_somebody_else_wrote_is_refused(tmp_path: Path) -> None:
    planning = planning_at(tmp_path, "meta-agent")
    dest = tmp_path / "units"
    dest.mkdir()
    mine = dest / timers.unit_names(planning)[0]
    mine.write_text("[Unit]\nDescription=mine\n")

    change = timers.install(planning, dest=dest, run=fake_run([]))

    assert [path.name for path in change.refused] == [mine.name]
    assert mine.read_text() == "[Unit]\nDescription=mine\n"
    assert len(change.written) == len(timers.BASE_UNITS) - 1, "the rest still land"


# --- enabling and removing ----------------------------------------------------------


def test_installing_schedules_them(tmp_path: Path) -> None:
    """What installing a timer is for. Written but not enabled is the failure
    that looks most like success: `abk status` answers perfectly while no tick
    has happened in a week."""
    planning = planning_at(tmp_path, "meta-agent")
    calls: list[list[str]] = []

    timers.install(planning, dest=tmp_path / "d", run=fake_run(calls))

    enabled = [argv[-1] for argv in calls if "enable" in argv]
    assert enabled == [n for n in timers.unit_names(planning) if n.endswith(".timer")]


def test_the_services_beside_them_are_never_enabled(tmp_path: Path) -> None:
    """Enabling a `.service` would run it at boot, outside the schedule that is
    the whole point of the timer beside it."""
    planning = planning_at(tmp_path, "meta-agent")
    calls: list[list[str]] = []

    timers.install(planning, dest=tmp_path / "d", run=fake_run(calls))

    assert not any(argv[-1].endswith(".service") for argv in calls if "enable" in argv)


def test_a_caller_that_will_schedule_them_itself_can_say_so(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    timers.install(
        planning_at(tmp_path, "meta-agent"), dest=tmp_path / "d", run=fake_run(calls), enable=False
    )

    assert calls == [["systemctl", "--user", "daemon-reload"]]


def test_enabling_again_is_harmless(tmp_path: Path) -> None:
    """`enable --now` is idempotent, so it runs whether or not a file changed —
    which is what repairs a unit that was written but never scheduled."""
    planning = planning_at(tmp_path, "meta-agent")
    dest = tmp_path / "d"
    timers.install(planning, dest=dest, run=fake_run([]))
    calls: list[list[str]] = []

    change = timers.install(planning, dest=dest, run=fake_run(calls))

    assert change.written == ()
    assert [argv[-1] for argv in calls if "enable" in argv] == [
        n for n in timers.unit_names(planning) if n.endswith(".timer")
    ]


def test_removing_stops_the_timers_before_deleting_them(tmp_path: Path) -> None:
    """A unit file deleted from under a running timer leaves the manager holding
    a job it can no longer describe."""
    planning = planning_at(tmp_path, "meta-agent")
    dest = tmp_path / "units"
    timers.install(planning, dest=dest, run=fake_run([]))
    calls: list[list[str]] = []

    timers.remove(planning, dest=dest, run=fake_run(calls))

    disabled = [argv for argv in calls if "disable" in argv]
    assert disabled, "the timers are disabled"
    assert all(argv[-1].endswith(".timer") for argv in disabled)
    assert calls.index(disabled[0]) < calls.index(["systemctl", "--user", "daemon-reload"])
    assert not list(dest.iterdir())


def test_removing_what_is_not_installed_is_not_an_error(tmp_path: Path) -> None:
    change = timers.remove(planning_at(tmp_path, "meta-agent"), dest=tmp_path / "none")

    assert change.removed == ()


def test_a_dry_run_touches_nothing(tmp_path: Path) -> None:
    planning = planning_at(tmp_path, "meta-agent")
    dest = tmp_path / "units"
    calls: list[list[str]] = []

    change = timers.install(planning, dest=dest, run=fake_run(calls), dry_run=True)

    assert len(change.written) == len(timers.BASE_UNITS)
    assert not dest.exists()
    assert calls == []
