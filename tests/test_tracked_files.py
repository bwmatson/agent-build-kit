"""The helper that yields the tracked files a repo-wide guard reads (spec: repo-wide-guards)."""

from __future__ import annotations

from pathlib import Path

from tests.factories import commit_files, init_repo
from tests.tracked_files import guarded_files, planning_dirs

TREE = {
    "docs/a.md": "a\n",
    "docs/b.txt": "b\n",
    "src/m.py": "m\n",
    "README.md": "r\n",
    "openspec/changes/x/proposal.md": "p\n",
    "runs/notes.md": "n\n",
    "runs/units.json": "{}\n",
    "node_modules/b.md": "b\n",
    ".hidden/c.md": "c\n",
}


def build(root: Path, files: dict[str, str] = TREE) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def relative(root: Path, found: list[Path]) -> list[str]:
    return [path.relative_to(root).as_posix() for path in found]


def test_planning_content_is_left_out_by_default(tmp_path: Path) -> None:
    root = build(tmp_path)

    found = relative(root, guarded_files(root, suffixes=[".md"], specs=False))

    assert found == ["README.md", "docs/a.md"]


def test_the_specification_folder_is_added_on_request_and_the_state_folder_is_not(
    tmp_path: Path,
) -> None:
    root = build(tmp_path)

    found = relative(root, guarded_files(root, suffixes=[".md"], specs=True))

    assert found == ["README.md", "docs/a.md", "openspec/changes/x/proposal.md"]


def test_under_names_and_suffixes_narrow_the_result_and_it_is_sorted(tmp_path: Path) -> None:
    root = build(tmp_path)

    assert relative(root, guarded_files(root, under=["src", "docs"])) == [
        "docs/a.md",
        "docs/b.txt",
        "src/m.py",
    ]
    assert relative(root, guarded_files(root, under=["docs"], suffixes=[".txt"])) == ["docs/b.txt"]
    assert relative(root, guarded_files(root, under=["src"], names=["README.md", "absent.md"])) == [
        "README.md",
        "src/m.py",
    ]


def test_a_root_file_named_under_the_state_folder_is_yielded(tmp_path: Path) -> None:
    root = build(tmp_path)

    found = relative(root, guarded_files(root, under=["docs"], names=["runs/units.json"]))

    assert found == ["docs/a.md", "docs/b.txt", "runs/units.json"]


def test_the_planning_folders_come_from_abk_yaml(tmp_path: Path) -> None:
    root = build(
        tmp_path,
        {
            "abk.yaml": "planning:\n  specs_dir: specs\n  state_dir: state\n",
            "specs/c.md": "c\n",
            "openspec/d.md": "d\n",
            "state/e.md": "e\n",
            "runs/f.md": "f\n",
        },
    )

    assert relative(root, guarded_files(root, suffixes=[".md"])) == ["openspec/d.md", "runs/f.md"]
    assert relative(root, guarded_files(root, suffixes=[".md"], specs=True)) == [
        "openspec/d.md",
        "runs/f.md",
        "specs/c.md",
    ]
    dirs = planning_dirs(root)
    assert (dirs.specs_dir, dirs.state_dir) == ("specs", "state")


def test_a_missing_abk_yaml_gives_the_defaults(tmp_path: Path) -> None:
    dirs = planning_dirs(tmp_path)

    assert (dirs.specs_dir, dirs.state_dir) == ("openspec", "runs")


def test_an_unset_state_folder_gives_the_default(tmp_path: Path) -> None:
    build(tmp_path, {"abk.yaml": "planning:\n  specs_dir: specs\n"})

    dirs = planning_dirs(tmp_path)

    assert (dirs.specs_dir, dirs.state_dir) == ("specs", "runs")


def test_in_a_git_repository_an_untracked_file_is_not_yielded(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "repo")
    commit_files(root, "start", {"docs/tracked.md": "t\n"})
    (root / "docs" / "untracked.md").write_text("u\n")

    found = relative(root, guarded_files(root, suffixes=[".md"]))

    assert found == ["docs/tracked.md"]


def test_outside_a_git_repository_the_tree_is_walked(tmp_path: Path) -> None:
    root = build(tmp_path, {"docs/loose.md": "l\n"})

    assert relative(root, guarded_files(root, suffixes=[".md"])) == ["docs/loose.md"]
