"""What every real sandbox backend promises, run with the real restrictions in subprocesses.

Each backend is a parameter (the `backend` fixture in `conftest.py`); one that cannot be
applied on this machine is skipped with its own cause.
"""

from __future__ import annotations

import sys

import pytest

from agent_build_kit.sandboxes import SandboxBackend
from tests.sandboxes.landlock_support import Scene, launcher_args, run_confined

# A write route that may land on a file, as an argv; `{path}` is where it writes.
WRITE_ROUTES = {
    "redirect": ["sh", "-c", "echo pwned > {path}"],
    "interpreter": [
        sys.executable,
        "-c",
        "import sys; open(sys.argv[1], 'w').write('pwned')",
        "{path}",
    ],
    "append": ["sh", "-c", "echo pwned >> {path}"],
    "sed": ["sed", "-i", "s/original/pwned/", "{path}"],
    "cp": ["cp", "{source}", "{path}"],
}


def _route(name: str, scene: Scene, path: str) -> list[str]:
    return [part.format(path=path, source=scene.movable) for part in WRITE_ROUTES[name]]


def _refused(result_stderr: str) -> bool:
    text = result_stderr.lower()
    return "permission denied" in text or "operation not permitted" in text


@pytest.mark.parametrize("route", sorted(WRITE_ROUTES))
def test_a_write_inside_the_grant_works(backend: SandboxBackend, scene: Scene, route: str) -> None:
    result = run_confined(backend, scene.policy(), _route(route, scene, str(scene.inside)))

    assert result.returncode == 0, result.stderr
    assert scene.inside.read_text() != "original\n"


@pytest.mark.parametrize("route", sorted(WRITE_ROUTES))
def test_a_write_outside_the_grant_fails_by_every_command(
    backend: SandboxBackend, scene: Scene, route: str
) -> None:
    result = run_confined(backend, scene.policy(), _route(route, scene, str(scene.target)))

    assert result.returncode != 0
    assert _refused(result.stderr), result.stderr
    assert scene.target.read_text() == "original\n"


def test_a_move_over_a_protected_file_fails(backend: SandboxBackend, scene: Scene) -> None:
    result = run_confined(backend, scene.policy(), ["mv", str(scene.movable), str(scene.target)])

    assert result.returncode != 0
    assert _refused(result.stderr), result.stderr
    assert scene.target.read_text() == "original\n"
    assert scene.movable.exists()


def test_a_move_out_of_a_protected_folder_fails(backend: SandboxBackend, scene: Scene) -> None:
    result = run_confined(
        backend, scene.policy(), ["mv", str(scene.target), str(scene.granted / "taken.txt")]
    )

    assert result.returncode != 0
    assert scene.target.read_text() == "original\n"
    assert not (scene.granted / "taken.txt").exists()


def test_a_write_through_a_symlink_in_a_granted_folder_fails(
    backend: SandboxBackend, scene: Scene
) -> None:
    result = run_confined(backend, scene.policy(), ["sh", "-c", f"echo pwned > {scene.link}"])

    assert result.returncode != 0
    assert _refused(result.stderr), result.stderr
    assert scene.target.read_text() == "original\n"


def test_a_write_by_a_dotdot_path_fails(backend: SandboxBackend, scene: Scene) -> None:
    sneaky = scene.granted / ".." / "protected" / scene.target.name

    result = run_confined(backend, scene.policy(), ["sh", "-c", f"echo pwned > {sneaky}"])

    assert result.returncode != 0
    assert _refused(result.stderr), result.stderr
    assert scene.target.read_text() == "original\n"


def test_a_child_shell_cannot_write_outside_the_grant(
    backend: SandboxBackend, scene: Scene
) -> None:
    inner = f"sh -c 'sh -c \"echo pwned > {scene.target}\"'"

    result = run_confined(backend, scene.policy(), ["sh", "-c", inner])

    assert result.returncode != 0
    assert scene.target.read_text() == "original\n"


def test_a_nested_launcher_asking_for_wider_rights_cannot_write(
    backend: SandboxBackend, scene: Scene
) -> None:
    wider = scene.policy().model_copy(update={"write": (scene.granted, scene.protected)})
    nested = backend.command(wider, ["sh", "-c", f"echo pwned > {scene.target}"])
    assert launcher_args(nested), "the backend's command has no policy file"

    result = run_confined(backend, scene.policy(), nested)

    assert result.returncode != 0
    assert scene.target.read_text() == "original\n"


def test_privileges_cannot_grow_inside(backend: SandboxBackend, scene: Scene) -> None:
    result = run_confined(
        backend, scene.policy(), ["sh", "-c", "grep '^NoNewPrivs' /proc/self/status"]
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-1] == "1"


def test_sudo_is_blocked(backend: SandboxBackend, scene: Scene) -> None:
    result = run_confined(backend, scene.policy(), ["sudo", "-n", "true"])

    assert result.returncode != 0


def test_device_files_work(backend: SandboxBackend, scene: Scene) -> None:
    script = "echo x > /dev/null && head -c 4 /dev/urandom | wc -c"

    result = run_confined(backend, scene.policy(), ["sh", "-c", script])

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "4"
