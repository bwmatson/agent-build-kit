"""The strict guard (spec: test-kind-names, "An old spelling is found by the guard")

Any old spelling in a source, test or document file fails the guard naming the file and line;
the compatibility module, the rename tool and their tests are exempt; the repository passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.old_test_kind_names import old_spelling_problems

REPOSITORY = Path(__file__).resolve().parents[1]
# Built in parts so this file carries no old spelling for the guard to find.
TIER = "ti" + "er"
OLD_GATE = f"{TIER}2_gate"


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


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
    "spelling", [f"{TIER.title()} 1", f"{TIER.upper()}_2", f"{TIER}-2", f"{TIER}1"]
)
def test_each_spelling_and_case_is_found(tmp_path: Path, spelling: str) -> None:
    root = tree(tmp_path, {"src/step.py": f"# the {spelling} run\n"})

    assert any("src/step.py:1" in p for p in old_spelling_problems(root))


def test_a_file_named_for_an_old_spelling_fails(tmp_path: Path) -> None:
    root = tree(tmp_path, {f"tests/{TIER}2_fakes.py": "x = 1\n"})

    assert any(f"{TIER}2_fakes.py" in p for p in old_spelling_problems(root))


@pytest.mark.parametrize(
    "path",
    [
        "src/agent_build_kit/compat_names.py",
        "src/agent_build_kit/rename_test_kinds.py",
        "tests/test_compat_names.py",
        "tests/test_rename_test_kinds_shims.py",
        "CHANGELOG.md",
    ],
)
def test_the_compatibility_module_the_tool_and_their_tests_are_exempt(
    tmp_path: Path, path: str
) -> None:
    root = tree(tmp_path, {path: f"OLD = '{OLD_GATE}'\n"})

    assert old_spelling_problems(root) == []


def test_a_shim_module_is_no_longer_exempt(tmp_path: Path) -> None:
    shim = "from agent_build_kit.pipeline.e2e import *\n"
    root = tree(tmp_path, {f"src/agent_build_kit/pipeline/{TIER}2.py": shim})

    assert old_spelling_problems(root) != []


def test_text_with_only_the_new_names_passes(tmp_path: Path) -> None:
    root = tree(tmp_path, {"src/step.py": "KINDS = ('unit-test', 'e2e-test')\n"})

    assert old_spelling_problems(root) == []


def test_the_repository_carries_no_old_spelling() -> None:
    assert old_spelling_problems(REPOSITORY) == []
