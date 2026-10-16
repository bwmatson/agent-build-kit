"""The tool that rewrites the old test-kind spellings over the paths it is given (spec:
test-kind-names, "The rename is applied by a repeatable tool")."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent_build_kit import rename_test_kinds
from tests.factories import commit_files, git, init_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path / "repo")


def test_each_old_spelling_is_rewritten_to_the_form_the_table_gives(repo: Path) -> None:
    commit_files(
        repo,
        "seed",
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


def test_a_bare_identifier_becomes_the_identifier_stem_and_a_quoted_tag_the_tag(
    repo: Path,
) -> None:
    source = 'def tier1(self):\n    pass\n\n\ntier2: bool = False\nx = "tier2"\n(tier2,) = x\n'
    commit_files(repo, "seed", {"a.py": source})

    rename_test_kinds.rename_paths(repo, [repo / "a.py"])

    result = (repo / "a.py").read_text()
    assert "def unit_test(self):" in result
    assert "e2e: bool = False" in result
    assert 'x = "e2e-test"' in result
    ast.parse(result)


def test_only_tracked_files_are_rewritten_or_moved(repo: Path) -> None:
    commit_files(repo, "seed", {"pkg/tier2.py": "x = 1\n", ".gitignore": "__pycache__/\n"})
    cache = repo / "pkg/__pycache__"
    cache.mkdir()
    (cache / "tier2.cpython-314.pyc").write_bytes(b"tier2 \x00 tier2")

    rename_test_kinds.rename_paths(repo, [repo / "pkg"])

    assert (repo / "pkg/e2e.py").exists()
    assert (cache / "tier2.cpython-314.pyc").read_bytes() == b"tier2 \x00 tier2"


def test_a_renamed_file_is_recorded_as_a_rename_in_git(repo: Path) -> None:
    commit_files(repo, "seed", {"pkg/tier2_gate.py": "x = 1\n"})

    rename_test_kinds.rename_paths(repo, [repo / "pkg"])

    assert git(repo, "ls-files", "pkg").split() == ["pkg/e2e_gate.py"]


def test_line_endings_are_kept(repo: Path) -> None:
    commit_files(repo, "seed", {"a.md": "x\n"})
    (repo / "a.md").write_bytes(b"tier 2\r\nmore\r\n")

    rename_test_kinds.rename_paths(repo, [repo / "a.md"])

    assert (repo / "a.md").read_bytes() == b"e2e-test\r\nmore\r\n"


def test_tier_one_is_rewritten_in_each_case_style(repo: Path) -> None:
    commit_files(repo, "seed", {"a.md": "tier1 Tier1 TIER1 tier 1\n"})

    rename_test_kinds.rename_paths(repo, [repo / "a.md"])

    assert (repo / "a.md").read_text() == "unit-test UnitTest UNIT_TEST unit-test\n"


def test_a_word_that_only_contains_the_spelling_is_left_alone(repo: Path) -> None:
    commit_files(repo, "seed", {"a.md": "frontier2 retier1ed tier20\n"})

    changed = rename_test_kinds.rename_paths(repo, [repo / "a.md"])

    assert changed == []
    assert (repo / "a.md").read_text() == "frontier2 retier1ed tier20\n"


def test_a_path_outside_the_root_is_refused_and_nothing_changes(repo: Path, tmp_path: Path) -> None:
    commit_files(repo, "seed", {"inside.md": "tier 2\n"})
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
    commit_files(repo, "seed", {"a.md": "tier 2\n"})

    assert rename_test_kinds.main(["--paths", str(repo / "a.md")], root=repo) == 0
    assert "a.md" in capsys.readouterr().out
    assert rename_test_kinds.main(["--paths", str(tmp_path)], root=repo) == 2
