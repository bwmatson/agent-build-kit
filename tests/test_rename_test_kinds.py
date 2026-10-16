"""The tool that rewrites the old test-kind spellings over the paths it is given (spec:
test-kind-names, "The rename is applied by a repeatable tool")."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import rename_test_kinds
from tests.factories import git, init_repo


def seed(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "seed")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path / "repo")


def test_each_old_spelling_is_rewritten_to_the_form_the_table_gives(repo: Path) -> None:
    seed(
        repo,
        {
            "pkg/tier2_gate.py": "class Tier2Result:\n    pass\n\nTIER2_MARKER = 1\n",
            "pkg/names.py": 'METRIC = "abk.tier2.test.time"\n',
            "docs/notes.md": "The tier 2 results are kept.\n",
            "tests/test_tier2_blocks.py": "def test_it() -> None:\n    pass\n",
        },
    )

    changed = rename_test_kinds.rename_paths(repo, [repo / "pkg", repo / "docs", repo / "tests"])

    assert (repo / "pkg/e2e_gate.py").read_text() == (
        "class E2eResult:\n    pass\n\nE2E_MARKER = 1\n"
    )
    assert not (repo / "pkg/tier2_gate.py").exists()
    assert (repo / "pkg/names.py").read_text() == 'METRIC = "abk.e2e.test.time"\n'
    assert (repo / "docs/notes.md").read_text() == "The e2e-test results are kept.\n"
    assert (repo / "tests/test_e2e_blocks.py").exists()
    assert not (repo / "tests/test_tier2_blocks.py").exists()
    assert {p.as_posix() for p in changed} >= {
        "pkg/e2e_gate.py",
        "pkg/names.py",
        "docs/notes.md",
        "tests/test_e2e_blocks.py",
    }


def test_tier_one_is_rewritten_in_each_case_style(repo: Path) -> None:
    seed(repo, {"a.md": "tier1 Tier1 TIER1 tier 1\n"})

    rename_test_kinds.rename_paths(repo, [repo / "a.md"])

    assert (repo / "a.md").read_text() == "unit-test UnitTest UNIT_TEST unit-test\n"


def test_a_word_that_only_contains_the_spelling_is_left_alone(repo: Path) -> None:
    seed(repo, {"a.md": "frontier2 retier1ed tier20\n"})

    changed = rename_test_kinds.rename_paths(repo, [repo / "a.md"])

    assert changed == []
    assert (repo / "a.md").read_text() == "frontier2 retier1ed tier20\n"


def test_a_path_outside_the_root_is_refused_and_nothing_changes(repo: Path, tmp_path: Path) -> None:
    seed(repo, {"inside.md": "tier 2\n"})
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "other.md").write_text("tier 2\n")

    with pytest.raises(rename_test_kinds.PathOutsideRoot):
        rename_test_kinds.rename_paths(repo, [repo / "inside.md", outside])

    assert (repo / "inside.md").read_text() == "tier 2\n"
    assert (outside / "other.md").read_text() == "tier 2\n"


def test_the_command_line_reports_changed_files_and_refuses_an_outside_path(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(repo, {"a.md": "tier 2\n"})

    assert rename_test_kinds.main(["--paths", str(repo / "a.md")], root=repo) == 0
    assert "a.md" in capsys.readouterr().out
    assert rename_test_kinds.main(["--paths", str(tmp_path)], root=repo) == 2
