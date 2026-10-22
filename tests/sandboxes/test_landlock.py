"""The Landlock backend: its probe, what it leaves ungoverned, and how its launcher fails."""

from __future__ import annotations

import errno
import os
import socket
import sys
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.sandboxes import Coverage, SandboxPolicy, landlock, launcher
from tests.sandboxes.landlock_support import (
    Scene,
    launcher_args,
    policy_for,
    require_working,
    run_confined,
)


class Exec:
    """Stands in for `os.execvp`: records the call instead of replacing the process."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, program: str, argv: list[str]) -> None:
        self.calls.append((program, argv))


def refusing(code: int):
    def restrict(lists: Mapping[str, list[str]]) -> None:
        raise OSError(code, os.strerror(code))

    return restrict


def started(policy: SandboxPolicy, marker: Path) -> list[str]:
    """The launcher's arguments for a command that would create `marker`."""
    return launcher_args(landlock.BACKEND.command(policy, ["touch", str(marker)]))


def test_the_backend_is_the_linux_one_and_is_chosen_on_linux() -> None:
    assert landlock.BACKEND.name == "landlock"
    assert landlock.BACKEND.platform == "linux"
    assert sandboxes.get("landlock") is landlock.BACKEND
    require_working(landlock.BACKEND)
    assert sandboxes.detect("linux") is landlock.BACKEND


def test_availability_reports_the_coverage_it_reaches() -> None:
    require_working(landlock.BACKEND)

    found = landlock.BACKEND.availability()

    assert found.ok
    assert found.coverage in (Coverage.PROCESS, Coverage.FILES)


def test_the_command_starts_the_given_argv_after_a_policy_file(tmp_path: Path) -> None:
    policy = policy_for([tmp_path])

    command = landlock.BACKEND.command(policy, ["echo", "hi"])

    assert command[command.index("--") + 1 :] == ["echo", "hi"]
    assert Path(launcher_args(command)[0]).is_file()


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A folder with a path short enough for a Unix socket's name."""
    with tempfile.TemporaryDirectory(prefix="abk-") as made:
        yield Path(made)


# Documented limits: what Landlock does not govern. A test here that starts failing means a
# later change made the sandbox stricter on purpose, and updates the line with it.
def test_chmod_is_not_governed(scene: Scene) -> None:
    require_working(landlock.BACKEND)
    scene.target.chmod(0o600)

    result = run_confined(landlock.BACKEND, scene.policy(), ["chmod", "640", str(scene.target)])

    assert result.returncode == 0, result.stderr
    assert scene.target.stat().st_mode & 0o777 == 0o640


def test_timestamps_are_not_governed(scene: Scene) -> None:
    require_working(landlock.BACKEND)
    script = "import os, sys; os.utime(sys.argv[1], (1000, 1000))"

    result = run_confined(
        landlock.BACKEND, scene.policy(), [sys.executable, "-c", script, str(scene.target)]
    )

    assert result.returncode == 0, result.stderr
    assert scene.target.stat().st_mtime == 1000


def test_a_path_name_unix_socket_is_reachable(scene: Scene, short_dir: Path) -> None:
    require_working(landlock.BACKEND)
    path = short_dir / "s"
    script = (
        "import socket, sys; s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); print('ok')"
    )
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        server.listen(1)

        result = run_confined(
            landlock.BACKEND, scene.policy(), [sys.executable, "-c", script, str(path)]
        )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_a_kernel_without_landlock_exits_97_naming_the_kernel(scene: Scene, tmp_path: Path) -> None:
    run = Exec()
    marker = tmp_path / "ran"

    with pytest.raises(SystemExit) as stopped:
        launcher.main(
            started(scene.policy(required=Coverage.FILES), marker),
            restrict=refusing(errno.ENOSYS),
            execvp=run,
        )

    assert stopped.value.code == launcher.EXIT_NOT_APPLIED == 97
    assert run.calls == []


def test_the_cause_of_a_kernel_without_landlock_is_printed(
    scene: Scene, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        launcher.main(
            started(scene.policy(), tmp_path / "ran"),
            restrict=refusing(errno.ENOSYS),
            execvp=Exec(),
        )

    err = capsys.readouterr().err
    assert "sandbox could not start" in err
    assert "kernel" in err


def test_landlock_disabled_at_boot_exits_97_and_says_so(
    scene: Scene, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Exec()

    with pytest.raises(SystemExit) as stopped:
        launcher.main(
            started(scene.policy(), tmp_path / "ran"),
            restrict=refusing(errno.EOPNOTSUPP),
            execvp=run,
        )

    err = capsys.readouterr().err
    assert stopped.value.code == 97
    assert "sandbox could not start" in err
    assert "disabled" in err
    assert run.calls == []


def test_required_none_runs_the_command_unconfined_and_says_so(
    scene: Scene, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Exec()
    marker = tmp_path / "ran"

    launcher.main(
        started(scene.policy(required=Coverage.NONE), marker),
        restrict=refusing(errno.ENOSYS),
        execvp=run,
    )

    assert run.calls == [("touch", ["touch", str(marker)])]
    assert "unconfined" in capsys.readouterr().err
