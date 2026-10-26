"""The Landlock backend: its probe, what it leaves ungoverned, and how its launcher fails."""

from __future__ import annotations

import ctypes
import errno
import os
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.sandboxes import Coverage, SandboxPolicy, held, landlock, launcher
from tests.sandboxes.landlock_support import (
    Scene,
    launcher_args,
    policy_for,
    readable_folders,
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


class FailingLibc:
    """Stands in for libc: every `syscall` fails with the errno it was given, as a kernel would."""

    def __init__(self, code: int) -> None:
        self.code = code

    def syscall(self, *args: object) -> int:
        ctypes.set_errno(self.code)
        return -1


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


def test_the_kernels_errno_reaches_the_launchers_message(
    scene: Scene, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def restrict(lists: Mapping[str, list[str]]) -> None:
        launcher.apply_restrictions(lists, FailingLibc(errno.ENOSYS))  # pyrefly: ignore

    with pytest.raises(SystemExit) as stopped:
        launcher.main(started(scene.policy(), tmp_path / "ran"), restrict=restrict, execvp=Exec())

    assert stopped.value.code == 97
    assert "kernel" in capsys.readouterr().err


def test_a_launcher_that_never_ran_the_command_is_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def crashing(self: object, policy: SandboxPolicy, argv: object) -> list[str]:
        return [sys.executable, "-c", "raise SystemExit(1)"]

    monkeypatch.setattr(landlock.Landlock, "command", crashing)

    assert landlock.BACKEND.availability().ok is False


def test_a_probe_that_times_out_is_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    def expire(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired("probe", 30)

    monkeypatch.setattr(subprocess, "run", expire)

    assert landlock.BACKEND.availability().ok is False


def test_the_launcher_removes_its_policy_file_once_read(scene: Scene, tmp_path: Path) -> None:
    args = started(scene.policy(required=Coverage.NONE), tmp_path / "ran")

    launcher.main(args, restrict=refusing(errno.ENOSYS), execvp=Exec())

    assert not Path(args[0]).exists()


def test_a_no_execute_path_is_listed_apart_from_the_read_paths(tmp_path: Path) -> None:
    kept, unrun = tmp_path / "kept", tmp_path / "unrun"
    given = policy_for([], read=[kept, unrun]).model_copy(update={"no_execute": (unrun,)})

    args = started(given, tmp_path / "ran")
    text = Path(args[0]).read_text().splitlines()
    Path(args[0]).unlink()

    assert f"no_execute={unrun}" in text
    assert f"read={unrun}" not in text
    assert f"read={kept}" in text


def test_a_no_execute_folder_is_read_and_not_run_and_stays_so_when_a_file_is_replaced(
    tmp_path: Path,
) -> None:
    require_working(landlock.BACKEND)
    folder, granted = tmp_path / "git", tmp_path / "granted"
    folder.mkdir()
    granted.mkdir()
    hook, packed = folder / "hook.sh", folder / "packed"
    hook.write_text("#!/bin/sh\necho ran\n")
    hook.chmod(0o755)
    packed.write_text("one\n")
    # The temp folder is left out of the system reads: it would grant the run beneath it.
    system = tuple(p for p in readable_folders() if p != Path(tempfile.gettempdir()).resolve())
    ready, replaced = granted / "ready", granted / "replaced"
    script = (
        f"cat {packed} && ! {hook} && : > {ready} && "
        f"until [ -e {replaced} ]; do sleep 0.02; done && cat {packed}"
    )

    def replace() -> None:
        lock = packed.with_name("packed.lock")
        lock.write_text("two\n")
        lock.replace(packed)
        replaced.touch()

    held_back = SandboxPolicy(
        write=(granted,),
        read=(*system, folder),
        hosts=(),
        required=Coverage.FILES,
        no_execute=(folder,),
    )
    done = held.run_replacing(landlock.BACKEND, held_back, script, ready=ready, replace=replace)

    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["one", "two"]
    open_to_run = held_back.model_copy(update={"no_execute": ()})
    control = run_confined(landlock.BACKEND, open_to_run, ["sh", "-c", str(hook)])
    assert control.stdout.strip() == "ran", "the control: a plain read grant runs it"
