"""The strict guard (spec: test-kind-names, "An old spelling is found by the guard")

Any old spelling in a source, test or document file fails the guard naming the file and line;
the compatibility module and its tests are exempt, the rename tool is not; the repository passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.old_test_kind_names import candidates, old_spelling_problems

REPOSITORY = Path(__file__).resolve().parents[1]
# Built in parts so this file carries no old spelling for the guard to find.
TIER = "ti" + "er"
OLD_GATE = f"{TIER}2_gate"
TOOL_MODULE = "rename_" + "test_kinds"


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def naming_the_tool(root: Path) -> list[str]:
    """`path:line` of each line of the files the guard scans that names the rename tool."""
    found = []
    for path in candidates(root):
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        found += [
            f"{path.relative_to(root).as_posix()}:{number}"
            for number, line in enumerate(lines, start=1)
            if TOOL_MODULE in line
        ]
    return found


@pytest.mark.parametrize(
    "path",
    [
        "src/agent_build_kit/pipeline/step.py",
        "tests/pipeline/test_step.py",
        "docs/guide.md",
        "web/src/panel.ts",
    ],
)
def test_an_old_spelling_fails_naming_the_file_and_line(tmp_path: Path, path: str) -> None:
    root = tree(tmp_path, {path: f"x = 1\nNAME = '{OLD_GATE}'\n"})

    problems = old_spelling_problems(root)

    assert len(problems) == 1
    assert f"{path}:2" in problems[0]


@pytest.mark.parametrize(
    "spelling",
    [
        f"{TIER.title()} 1",
        f"{TIER.upper()}_2",
        f"{TIER}-2",
        f"{TIER}1",
        f"{TIER}_two",
        f"{TIER} one",
    ],
)
def test_each_spelling_and_case_is_found(tmp_path: Path, spelling: str) -> None:
    root = tree(tmp_path, {"src/step.py": f"# the {spelling} run\n"})

    assert any("src/step.py:1" in p for p in old_spelling_problems(root))


@pytest.mark.parametrize("path", ["pyproject.toml", "scripts/ci_scope.py", ".github/ci.yml"])
def test_the_build_files_and_scripts_are_scanned(tmp_path: Path, path: str) -> None:
    root = tree(tmp_path, {path: f"# {OLD_GATE}\n"})

    assert any(f"{path}:1" in p for p in old_spelling_problems(root))


def test_a_file_named_for_an_old_spelling_fails(tmp_path: Path) -> None:
    root = tree(tmp_path, {f"tests/{TIER}2_fakes.py": "x = 1\n"})

    assert any(f"{TIER}2_fakes.py" in p for p in old_spelling_problems(root))


@pytest.mark.parametrize(
    "path",
    [
        "src/agent_build_kit/compat_names.py",
        "tests/test_compat_names.py",
        "tests/config/test_test_kind_settings_aliases.py",
        "docs/agent-efficient-coding-philosophy.md",
        "docs/risk-tiered-review-design.md",
        "CHANGELOG.md",
    ],
)
def test_the_compatibility_module_and_its_tests_are_exempt(tmp_path: Path, path: str) -> None:
    root = tree(tmp_path, {path: f"OLD = '{OLD_GATE}'\n"})

    assert old_spelling_problems(root) == []


@pytest.mark.parametrize(
    "path",
    [
        f"src/agent_build_kit/{TOOL_MODULE}.py",
        f"tests/test_{TOOL_MODULE}.py",
        f"tests/test_{TOOL_MODULE}_shims.py",
    ],
)
def test_the_rename_tool_and_its_tests_are_no_longer_exempt(tmp_path: Path, path: str) -> None:
    root = tree(tmp_path, {path: f"OLD = '{OLD_GATE}'\n"})

    assert any(f"{path}:1" in p for p in old_spelling_problems(root))


@pytest.mark.parametrize("path", ["docs/guide.md", "README.md", "AGENTS.md", "pyproject.toml"])
def test_a_file_naming_the_rename_tools_module_fails_a_source_search(
    tmp_path: Path, path: str
) -> None:
    root = tree(tmp_path, {path: f"Run `abk {TOOL_MODULE}` first.\n"})

    assert naming_the_tool(root) == [f"{path}:1"]


def test_no_file_of_the_repository_names_the_rename_tool() -> None:
    assert naming_the_tool(REPOSITORY) == []


def test_a_shim_module_is_no_longer_exempt(tmp_path: Path) -> None:
    shim = "from agent_build_kit.pipeline.e2e import *\n"
    root = tree(tmp_path, {f"src/agent_build_kit/pipeline/{TIER}2.py": shim})

    assert old_spelling_problems(root) != []


def test_text_with_only_the_new_names_passes(tmp_path: Path) -> None:
    root = tree(tmp_path, {"src/step.py": "KINDS = ('unit-test', 'e2e-test')\n"})

    assert old_spelling_problems(root) == []


def test_the_repository_carries_no_old_spelling() -> None:
    assert old_spelling_problems(REPOSITORY) == []
