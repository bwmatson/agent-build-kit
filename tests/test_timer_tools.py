"""A scheduled unit finds the tools a tick runs.

A unit starts with no login environment, so its PATH is what its template
says. On WSL the Azure CLI is the Windows install, which only a login shell's
PATH carries: every command a person ran worked, and the scheduled poll of the
Azure repo failed on each tick with nothing in the log. These tests cover the
three halves of that: the install puts the tool's directory on the unit's PATH,
`abk doctor` asks the *unit* rather than the terminal, and a failed poll is
said out loud.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit import timers
from agent_build_kit.cli.doctor import run_doctor
from agent_build_kit.installation import Installation
from tests.conftest import make_installation

WINDOWS_CLI = "/mnt/c/Program Files/Microsoft SDKs/Azure/CLI2/wbin"


def run_ok(argv, **kwargs):
    return subprocess.CompletedProcess(argv, 0, "enabled\n", "")


def mixed(tmp_path: Path) -> Installation:
    """One Azure DevOps repo and one GitHub repo, as this workspace has."""
    root = tmp_path / "planning"
    repos = {
        "azure": {
            "path": str(tmp_path / "azure"),
            "forge": "azure_devops",
            "azure_devops": {"org": "acme", "project": "Proj", "repo": "azure"},
        },
        "hub": {"path": str(tmp_path / "hub"), "slug": "example/hub"},
    }
    return make_installation(root, repos=repos)


def github_only(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning")


def finder(**found: str):
    """`which` answering from a table: every tool lives where it is told."""
    return lambda tool, path=None: found.get(tool)


ALL_IN_BASE = {"uv": "/usr/bin/uv", "claude": "/usr/bin/claude", "gh": "/usr/bin/gh"}


def path_of(text: str) -> str:
    line = next(line for line in text.splitlines() if line.startswith('Environment="PATH='))
    return line.removeprefix('Environment="PATH=').removesuffix('"')


# --- which tools, and where --------------------------------------------------------


def test_an_azure_repo_needs_az_and_a_github_repo_needs_gh(tmp_path: Path) -> None:
    assert timers.needed_tools(mixed(tmp_path)) == ["uv", "claude", "az", "gh"]


def test_a_github_only_installation_does_not_need_az(tmp_path: Path) -> None:
    assert "az" not in timers.needed_tools(github_only(tmp_path))


def test_a_tool_outside_the_base_path_adds_its_directory(tmp_path: Path) -> None:
    where = finder(**ALL_IN_BASE, az=f"{WINDOWS_CLI}/az")

    assert timers.tool_dirs(mixed(tmp_path), which=where) == (WINDOWS_CLI,)


def test_tools_already_on_the_base_path_add_nothing(tmp_path: Path) -> None:
    assert timers.tool_dirs(mixed(tmp_path), which=finder(**ALL_IN_BASE, az="/usr/bin/az")) == ()


def test_a_tool_nothing_can_find_adds_nothing(tmp_path: Path) -> None:
    """Doctor is what reports a missing tool; an install does not invent a path."""
    assert timers.tool_dirs(mixed(tmp_path), which=finder(**ALL_IN_BASE)) == ()


def test_two_tools_in_one_directory_add_it_once(tmp_path: Path) -> None:
    where = finder(uv="/opt/bin/uv", claude="/opt/bin/claude", gh="/usr/bin/gh", az="/opt/bin/az")

    assert timers.tool_dirs(mixed(tmp_path), which=where) == ("/opt/bin",)


# --- the rendered unit -------------------------------------------------------------


def test_every_service_carries_the_directory_at_the_end_of_its_path(tmp_path: Path) -> None:
    units = timers.render(tmp_path / "planning", (WINDOWS_CLI,))

    services = {name: text for name, text in units.items() if name.endswith(".service")}
    assert len(services) == 4
    for name, text in services.items():
        path = path_of(text).split(":")
        assert path[-1] == WINDOWS_CLI, name
        assert path.index("/usr/bin") < path.index(WINDOWS_CLI), "never ahead of a system tool"


def test_a_unit_without_tool_directories_is_what_it_always_was(tmp_path: Path) -> None:
    text = timers.render(tmp_path / "planning")[timers.unit_names(tmp_path / "planning")[0]]

    assert path_of(text) == (
        "%h/.local/bin:%h/.volta/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )


def test_a_percent_in_a_directory_is_not_read_as_a_specifier(tmp_path: Path) -> None:
    text = timers.render(tmp_path / "planning", ("/opt/50%/bin",))[
        timers.unit_names(tmp_path / "planning")[0]
    ]

    assert path_of(text).endswith(":/opt/50%%/bin")


def test_installing_writes_the_directory_and_reinstalling_changes_nothing(
    tmp_path: Path,
) -> None:
    planning, dest = tmp_path / "planning", tmp_path / "units"
    planning.mkdir()

    timers.install(planning, dest=dest, run=run_ok, tool_dirs=(WINDOWS_CLI,))
    again = timers.install(planning, dest=dest, run=run_ok, tool_dirs=(WINDOWS_CLI,))

    assert WINDOWS_CLI in (dest / timers.unit_names(planning)[0]).read_text()
    assert not again.written, "idempotent with the same directories"


def test_a_unit_written_before_the_tools_were_known_reads_as_out_of_date(
    tmp_path: Path,
) -> None:
    planning, dest = tmp_path / "planning", tmp_path / "units"
    planning.mkdir()
    timers.install(planning, dest=dest, run=run_ok)

    state = timers.report(planning, dest=dest, tool_dirs=(WINDOWS_CLI,))

    assert len(state.drifted) == 4


# --- asking the unit, not the terminal ---------------------------------------------


def installed(tmp_path: Path, inst: Installation, tool_dirs: tuple[str, ...]) -> Path:
    dest = tmp_path / "units"
    timers.install(inst.root, dest=dest, run=run_ok, tool_dirs=tool_dirs)
    return dest


def test_the_service_path_is_read_from_the_installed_unit(tmp_path: Path) -> None:
    inst = mixed(tmp_path)
    dest = installed(tmp_path, inst, (WINDOWS_CLI,))

    path = timers.service_path(inst.root, dest)

    assert path is not None
    assert path[-1] == WINDOWS_CLI
    assert str(Path.home() / ".local" / "bin") in path, "%h is expanded"
    assert timers.service_path(tmp_path / "elsewhere", dest) is None


def test_a_tool_on_the_terminal_but_not_the_unit_is_reported_with_its_fix(
    tmp_path: Path,
) -> None:
    inst = mixed(tmp_path)
    dest = installed(tmp_path, inst, ())
    where = finder(**ALL_IN_BASE, az=f"{WINDOWS_CLI}/az")

    assert timers.unreachable(inst, dest, which=where) == [("az", True)]


def test_a_tool_neither_can_find_is_reported_as_not_fixable_by_reinstalling(
    tmp_path: Path,
) -> None:
    inst = mixed(tmp_path)
    dest = installed(tmp_path, inst, ())

    assert timers.unreachable(inst, dest, which=finder(**ALL_IN_BASE)) == [("az", False)]


def test_after_the_install_that_adds_it_nothing_is_unreachable(tmp_path: Path) -> None:
    inst = mixed(tmp_path)
    where = finder(**ALL_IN_BASE, az=f"{WINDOWS_CLI}/az")
    dest = installed(tmp_path, inst, timers.tool_dirs(inst, which=where))

    assert timers.unreachable(inst, dest, which=where) == []


def test_no_installed_unit_means_nothing_to_report(tmp_path: Path) -> None:
    inst = mixed(tmp_path)

    assert timers.unreachable(inst, tmp_path / "empty", which=finder(**ALL_IN_BASE)) == []


def doctor_check(inst: Installation, dest: Path, where, name: str):
    (inst.root / "abk.yaml").write_text(_dump(inst))
    checks = run_doctor(inst.root / "abk.yaml", run=run_ok, which=where, units=dest)
    return [check for check in checks if check.name == name]


def _dump(inst: Installation) -> str:
    from agent_build_kit.config import dump

    return dump(inst.config)


def test_doctor_fails_when_the_service_cannot_find_a_tool_the_terminal_can(
    tmp_path: Path,
) -> None:
    inst = mixed(tmp_path)
    dest = installed(tmp_path, inst, ())
    where = lambda tool: ALL_IN_BASE.get(tool, f"{WINDOWS_CLI}/{tool}")  # noqa: E731

    [check] = doctor_check(inst, dest, where, "timer PATH")

    assert check.status == "FAIL"
    assert "az" in check.detail
    assert "abk install-timers" in check.fix


def test_doctor_is_quiet_once_the_unit_carries_the_directory(tmp_path: Path) -> None:
    inst = mixed(tmp_path)
    where = lambda tool: ALL_IN_BASE.get(tool, f"{WINDOWS_CLI}/{tool}")  # noqa: E731
    dest = installed(tmp_path, inst, timers.tool_dirs(inst, which=where))

    assert doctor_check(inst, dest, where, "timer PATH") == []
