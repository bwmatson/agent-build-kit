"""The guard against a `serial` marker (spec: test-markers).

A test or a configuration file that names the marker fails, naming the file; pytest also refuses
it through strict marker registration, and this conformance test covers the runners without it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.serial_marker import serial_marker_problems
from tests.tracked_files import ROOT

NAME = "serial"


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("tests/test_a.py", f"import pytest\n\n@pytest.mark.{NAME}\ndef test_a(): ...\n"),
        ("pyproject.toml", f'[tool.pytest.ini_options]\nmarkers = ["{NAME}: alone"]\n'),
        ("pytest.ini", f"[pytest]\naddopts = -m 'not {NAME}'\n"),
    ],
    ids=["a test", "pyproject", "pytest.ini"],
)
def test_a_python_test_or_configuration_naming_the_marker_fails_naming_the_file(
    tmp_path: Path, path: str, text: str
) -> None:
    root = tree(tmp_path, {path: text})

    problems = serial_marker_problems(root)

    assert len(problems) == 1
    assert path in problems[0]


def test_a_javascript_project_configuration_naming_the_marker_fails(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "package.json": f'{{"scripts": {{"test": "vitest --project {NAME}"}}}}\n',
            "vitest.config.ts": f"export default {{ test: {{ include: ['{NAME}/**'] }} }};\n",
        },
    )

    problems = serial_marker_problems(root)

    assert len(problems) == 2
    assert any("package.json" in p for p in problems)
    assert any("vitest.config.ts" in p for p in problems)


def test_a_longer_word_is_not_the_marker(tmp_path: Path) -> None:
    root = tree(tmp_path, {"tests/test_a.py": "# the serialiser and a serial_number\n"})

    assert serial_marker_problems(root) == []


def test_the_pipelines_wording_for_a_rerun_alone_is_not_the_marker(tmp_path: Path) -> None:
    text = f'assert "two {NAME} reruns" in prompt\nassert "{NAME} rerun " in line\n'
    root = tree(tmp_path, {"tests/test_a.py": text})

    assert serial_marker_problems(root) == []


def test_the_guards_own_files_and_the_changelog_may_name_it(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "tests/test_no_serial_marker_guard.py": f"NAME = '{NAME}'\n",
            "tests/serial_marker.py": f"WORD = '{NAME}'\n",
            "CHANGELOG.md": f"- The {NAME} pass is gone.\n",
            "tests/test_clean.py": "def test_clean(): ...\n",
        },
    )

    assert serial_marker_problems(root) == []


@pytest.mark.integration
def test_no_tracked_test_or_configuration_file_names_the_marker() -> None:
    assert serial_marker_problems(ROOT) == []
