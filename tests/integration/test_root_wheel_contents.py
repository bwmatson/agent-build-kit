"""The root project's wheel carries everything a non-editable install imports: the worker's modules
beside the rest, and the `abk.commands` entry point that registers `abk worker`
(spec: kit-has-a-worker-package)."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from agent_build_kit.cli import COMMANDS_GROUP
from tests.ecosystem_names import REPOSITORY_ROOT, WORKER_MODULES

BUILD_TIME_LIMIT = 300


@pytest.fixture(scope="module")
def wheel_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Each member of the root project's built wheel with its text (empty for a binary file)."""
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(REPOSITORY_ROOT)],
        check=True,
        capture_output=True,
        text=True,
        timeout=BUILD_TIME_LIMIT,
    )
    [built] = Path(out).glob("*.whl")
    with zipfile.ZipFile(built) as wheel:
        return {
            name: wheel.read(name).decode(errors="ignore")
            for name in wheel.namelist()
            if name.endswith((".py", ".txt"))
        }


@pytest.mark.integration
@pytest.mark.parametrize("module", WORKER_MODULES)
def test_the_root_wheel_carries_each_module_the_worker_package_holds(
    wheel_files: dict[str, str], module: str
) -> None:
    assert f"agent_build_kit/{module}" in wheel_files


@pytest.mark.integration
def test_the_root_wheel_carries_the_module_that_imports_the_worker_modules(
    wheel_files: dict[str, str],
) -> None:
    assert "agent_build_kit/cli/pipeline.py" in wheel_files


@pytest.mark.integration
def test_the_root_wheel_registers_abk_worker_as_a_command(wheel_files: dict[str, str]) -> None:
    [points] = [text for name, text in wheel_files.items() if name.endswith("entry_points.txt")]

    assert f"[{COMMANDS_GROUP}]" in points
    assert "worker = agent_build_kit.cli.worker:register" in points
