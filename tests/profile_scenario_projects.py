"""The tiny fixture project per toolchain profile that the scenario suite runs over."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.model import Frozen
from agent_build_kit.profiles.base import ToolchainProfile

PYTHON_PROJECT = {
    "pyproject.toml": (
        '[project]\nname = "tiny"\nversion = "0"\nrequires-python = ">=3.12"\ndependencies = []\n\n'
        '[dependency-groups]\ndev = ["pytest", "pytest-xdist"]\n\n'
        "[tool.uv]\npackage = false\n\n"
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["."]\n'
        'markers = ["serial: runs alone"]\n'
    ),
    "calc.py": "def add(a, b):\n    return a + b\n",
    "other.py": "def double(x):\n    return x * 2\n",
    "tests/test_calc.py": "from calc import add\n\n\ndef test_adds():\n    assert add(1, 2) == 3\n",
    "tests/test_other.py": (
        "from other import double\n\n\ndef test_doubles():\n    assert double(2) == 4\n"
    ),
}
NODE_PROJECT = {
    "package.json": '{"name": "tiny", "version": "0.0.0", "type": "module"}\n',
    "src/calc.ts": "export const add = (a: number, b: number): number => a + b;\n",
    "src/other.ts": "export const double = (x: number): number => x * 2;\n",
    "src/calc.test.ts": (
        "import { expect, test } from 'vitest';\n"
        "import { add } from './calc';\n\n"
        "test('adds', () => {\n  expect(add(1, 2)).toBe(3);\n});\n"
    ),
    "src/other.test.ts": (
        "import { expect, test } from 'vitest';\n"
        "import { double } from './other';\n\n"
        "test('doubles', () => {\n  expect(double(2)).toBe(4);\n});\n"
    ),
}


class Scenario(Frozen):
    """What differs between the fixture projects: their files, and the tests each case adds."""

    files: dict[str, str]
    passing_id: str  # a test of the project that passes, and reaches `changed_file`
    new_path: str
    new_id: str
    new_failing: str  # the new test's source when it fails by an assertion
    new_passing: str  # and when it passes
    changed_file: str
    changed_source: str  # `changed_file` after a one-file change that breaks `passing_id`


class Broken(Frozen):
    """A test that always fails, written beside the project's own files."""

    path: str
    test_id: str
    source: str


class Run(Frozen):
    output: str
    returncode: int


SCENARIOS = {
    "python-uv": Scenario(
        files=PYTHON_PROJECT,
        passing_id="tests/test_calc.py::test_adds",
        new_path="tests/test_new.py",
        new_id="tests/test_new.py::test_new",
        new_failing="from calc import add\n\n\ndef test_new():\n    assert add(1, 1) == 3\n",
        new_passing="from calc import add\n\n\ndef test_new():\n    assert add(1, 1) == 2\n",
        changed_file="calc.py",
        changed_source="def add(a, b):\n    return a - b\n",
    ),
    "node-npm": Scenario(
        files=NODE_PROJECT,
        passing_id="src/calc.test.ts::adds",
        new_path="src/new.test.ts",
        new_id="src/new.test.ts::new",
        new_failing=(
            "import { expect, test } from 'vitest';\n"
            "import { add } from './calc';\n\n"
            "test('new', () => {\n  expect(add(1, 1)).toBe(3);\n});\n"
        ),
        new_passing=(
            "import { expect, test } from 'vitest';\n"
            "import { add } from './calc';\n\n"
            "test('new', () => {\n  expect(add(1, 1)).toBe(2);\n});\n"
        ),
        changed_file="src/calc.ts",
        changed_source="export const add = (a: number, b: number): number => a - b;\n",
    ),
}
BROKEN = {
    "python-uv": Broken(
        path="tests/test_broken.py",
        test_id="tests/test_broken.py::test_broken",
        source="def test_broken():\n    assert False\n",
    ),
    "node-npm": Broken(
        path="src/broken.test.ts",
        test_id="src/broken.test.ts::broken",
        source=(
            "import { expect, test } from 'vitest';\n\n"
            "test('broken', () => {\n  expect(1).toBe(2);\n});\n"
        ),
    ),
}


class ScenarioProject:
    """A fixture project in a folder, run through the profile's own commands."""

    name: str
    profile: ToolchainProfile
    scenario: Scenario
    broken: Broken
    root: Path
    seed: Path

    def __init__(self, name: str, root: Path) -> None:
        assert name in SCENARIOS and name in BROKEN, f"{name} has no scenario project"
        self.name = name
        self.profile = profiles.get(name)
        self.scenario = SCENARIOS[name]
        self.broken = BROKEN[name]
        self.root = root
        self.seed = root.parent / f"{root.name}-seed" / "affected"
        self.seed.parent.mkdir()
        self.write(self.scenario.files)

    def write(self, files: dict[str, str]) -> None:
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            before = path.stat().st_mtime_ns if path.exists() else 0
            path.write_text(text)
            # A same-size edit within a second of a run is not seen by a compiled-module cache.
            later = max(before, path.stat().st_mtime_ns) + 2_000_000_000
            os.utime(path, ns=(later, later))

    def run(self, command: str | list[str]) -> Run:
        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTEST_ADDOPTS")}
        env["npm_config_yes"] = "true"
        done = subprocess.run(
            command,
            shell=isinstance(command, str),
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return Run(output=done.stdout + done.stderr, returncode=done.returncode)

    def full_run(self) -> tuple[list[str], Run]:
        """The project's first full-suite command and its run."""
        command = self.profile.test_commands_all(self.root, root_extras=[])[0]
        return command, self.run(command)

    def counts(self, output: str) -> tuple[int, int]:
        passed, failed, _, _ = self.profile.parse_test_summary(output)
        return passed, failed
