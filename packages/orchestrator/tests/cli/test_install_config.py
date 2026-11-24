"""`abk install-config` (spec: config-install): what a builder may install through the kit.

Each test runs the real command line from a real git worktree of a fixture repo, and checks what
the worktree holds afterwards.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import WorkspaceConfig, dump
from tests.conftest import make_installation
from tests.factories import git, init_repo

PRE_COMMIT = "repos: []\n"
TARGET = "pkg/.pre-commit-config.yaml"


@dataclass
class Tree:
    root: Path
    config: Path

    def stage(self, content: str = PRE_COMMIT, name: str = "p.yaml") -> str:
        staged = self.root / ".abk" / "proposed" / name
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(content)
        return f".abk/proposed/{name}"

    def run(self, staged: str, target: str) -> int:
        return main(["--config", str(self.config), "install-config", staged, target])

    def files(self) -> set[str]:
        return {
            str(path.relative_to(self.root))
            for path in self.root.rglob("*")
            if ".git" not in path.relative_to(self.root).parts and path.is_file()
        }


def make_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **builders: object) -> Tree:
    repo = init_repo(tmp_path / "app")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "keep.txt").write_text("keep\n")
    git(repo, "add", "pkg")
    git(repo, "commit", "-q", "-m", "base")
    root = tmp_path / "trees" / "unit"
    git(repo, "worktree", "add", "-q", "-b", "spec/feature/1", str(root))
    overrides = dict(builders=builders) if builders else {}
    installation = make_installation(tmp_path / "planning", **overrides)
    config = installation.root / "abk.yaml"
    config.write_text(dump(installation.config))
    monkeypatch.chdir(root)
    return Tree(root, config)


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tree:
    return make_tree(tmp_path, monkeypatch)


def test_a_staged_file_is_installed_at_the_target(tree: Tree) -> None:
    staged = tree.stage("repos:\n  - repo: local\n")

    code = tree.run(staged, TARGET)

    assert code == 0
    installed = tree.root / TARGET
    assert installed.read_text() == "repos:\n  - repo: local\n"
    assert (
        installed.stat().st_mode & 0o777 == (tree.root / "pkg" / "keep.txt").stat().st_mode & 0o777
    )


def test_a_target_through_dotdot_is_refused_and_nothing_is_written(
    tree: Tree, capsys: pytest.CaptureFixture[str]
) -> None:
    staged = tree.stage()
    before = tree.files()

    code = tree.run(staged, "../outside/.pre-commit-config.yaml")

    assert code != 0
    assert "../outside/.pre-commit-config.yaml" in capsys.readouterr().err
    assert not (tree.root.parent / "outside").exists()
    assert tree.files() == before


def test_a_target_through_a_symlink_out_of_the_worktree_is_refused(
    tree: Tree, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    os.symlink(outside, tree.root / "link")
    staged = tree.stage()

    code = tree.run(staged, "link/.pre-commit-config.yaml")

    assert code != 0
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("target", ["CLAUDE.md", ".git/hooks/pre-commit"])
def test_a_name_off_the_allow_list_is_refused_naming_the_allow_list(
    tree: Tree, target: str, capsys: pytest.CaptureFixture[str]
) -> None:
    staged = tree.stage("text\n")
    before = tree.files()

    code = tree.run(staged, target)

    assert code != 0
    assert ".pre-commit-config.yaml" in capsys.readouterr().err
    assert tree.files() == before


def test_a_staged_file_outside_the_staging_directory_is_refused(tree: Tree) -> None:
    (tree.root / "pkg" / "loose.yaml").write_text(PRE_COMMIT)

    code = tree.run("pkg/loose.yaml", TARGET)

    assert code != 0
    assert not (tree.root / TARGET).exists()


def test_a_staged_symlink_is_refused(tree: Tree) -> None:
    # Inside the staging directory, so only the symlink rule can refuse it.
    tree.stage()
    os.symlink("p.yaml", tree.root / ".abk" / "proposed" / "link.yaml")

    code = tree.run(".abk/proposed/link.yaml", TARGET)

    assert code != 0
    assert not (tree.root / TARGET).exists()


@pytest.mark.parametrize("linked", [".abk", ".abk/proposed"])
def test_a_symlinked_staging_directory_out_of_the_worktree_is_refused(
    tree: Tree, tmp_path: Path, linked: str
) -> None:
    outside = tmp_path / "outside"
    (outside / "proposed").mkdir(parents=True)
    (outside / "proposed" / "token.yaml").write_text(PRE_COMMIT)
    if linked == ".abk":
        os.symlink(outside, tree.root / ".abk", target_is_directory=True)
    else:
        (tree.root / ".abk").mkdir()
        os.symlink(outside / "proposed", tree.root / ".abk" / "proposed", target_is_directory=True)

    code = tree.run(".abk/proposed/token.yaml", TARGET)

    assert code != 0
    assert not (tree.root / TARGET).exists()


def test_a_yaml_target_that_does_not_parse_is_refused_with_the_parse_error(
    tree: Tree, capsys: pytest.CaptureFixture[str]
) -> None:
    staged = tree.stage("repos: [unclosed\n")

    code = tree.run(staged, TARGET)

    assert code != 0
    assert "line" in capsys.readouterr().err
    assert not (tree.root / TARGET).exists()


def test_a_name_added_under_installable_files_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = make_tree(tmp_path, monkeypatch, installable_files=[".custom.yaml"])
    staged = tree.stage("a: 1\n")

    code = tree.run(staged, "pkg/.custom.yaml")

    assert code == 0
    assert (tree.root / "pkg" / ".custom.yaml").read_text() == "a: 1\n"


@pytest.mark.parametrize(
    "name", ["sub/.custom.yaml", "..\\x.yaml", "../x.yaml", "/x.yaml", "*.yaml"]
)
def test_a_name_with_a_path_separator_is_refused_when_the_config_loads(name: str) -> None:
    with pytest.raises(ValidationError, match="installable_files"):
        WorkspaceConfig.model_validate({"builders": {"installable_files": [name]}})


def test_a_failed_install_leaves_no_temporary_file(tree: Tree) -> None:
    staged = tree.stage()
    # A directory where the file belongs: the install cannot replace it.
    (tree.root / TARGET).mkdir()

    code = tree.run(staged, TARGET)

    assert code != 0
    assert sorted(path.name for path in (tree.root / "pkg").iterdir()) == [
        ".pre-commit-config.yaml",
        "keep.txt",
    ]
    assert list((tree.root / TARGET).iterdir()) == []
