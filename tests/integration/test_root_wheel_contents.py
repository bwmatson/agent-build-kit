"""The root project's wheel carries the root package's modules only: the worker's and the
orchestrator's modules, the `abk` script and the `abk.commands` entry point that registers
`abk worker` belong to the packages' own distributions
(spec: kit-has-a-worker-package, kit-has-an-orchestrator-package)."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from agent_build_kit.cli import COMMANDS_GROUP
from tests.ecosystem_names import WORKER_MODULES
from tests.tracked_files import ROOT

BUILD_TIME_LIMIT = 300


@pytest.fixture(scope="module")
def wheel_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Each member of the root project's built wheel with its text (empty for a binary file)."""
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(ROOT)],
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
def test_the_root_wheel_leaves_each_module_the_worker_package_holds_to_that_package(
    wheel_files: dict[str, str], module: str
) -> None:
    assert f"agent_build_kit/{module}" not in wheel_files


@pytest.mark.integration
def test_the_root_wheel_leaves_the_orchestrators_modules_to_its_package(
    wheel_files: dict[str, str],
) -> None:
    assert "agent_build_kit/cli/pipeline.py" not in wheel_files


@pytest.mark.integration
def test_the_root_wheel_leaves_the_abk_script_and_the_worker_command_to_the_packages(
    wheel_files: dict[str, str],
) -> None:
    points = [text for name, text in wheel_files.items() if name.endswith("entry_points.txt")]

    assert all(f"[{COMMANDS_GROUP}]" not in text and "abk =" not in text for text in points)
