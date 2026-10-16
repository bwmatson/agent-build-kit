"""`build_commit(only=...)` stages, checks and commits just the pathspecs it is given; without
`only` it stages everything, as a unit's commit does (spec: planning-state-paths). Real git;
the gate is a function that records what was staged when it ran.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.wiring import CommitRejected, build_commit
from tests.environment_fakes import FakeEnvironment, repo_config
from tests.factories import git, init_repo

LOCK = "deps.lock"
ALL_EDITED = [
    "abk.yaml",
    "openspec/changes/feature/design.md",
    "openspec/changes/feature/tasks.md",
    "src/main.py",
]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    for name, text in {
        "README.md": "base\n",
        "openspec/changes/feature/tasks.md": "tasks\n",
        "src/main.py": "main\n",
        LOCK: "as committed\n",
    }.items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(text)
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


def edit(work: Path) -> None:
    """A change under `openspec/`, a modified source file and a new top-level file."""
    (work / "openspec/changes/feature/tasks.md").write_text("edited\n")
    (work / "openspec/changes/feature/design.md").write_text("new\n")
    (work / "src/main.py").write_text("edited\n")
    (work / "abk.yaml").write_text("repos: {}\n")


def committed(work: Path) -> list[str]:
    return sorted(git(work, "show", "--name-only", "--format=", "HEAD").split())


def test_only_stages_and_commits_those_pathspecs_and_leaves_the_rest_unstaged(repo: Path) -> None:
    edit(repo)

    made = build_commit(only=("openspec", "abk.yaml"))("docs: plan", cwd=repo)

    assert made == 1
    assert committed(repo) == [
        "abk.yaml",
        "openspec/changes/feature/design.md",
        "openspec/changes/feature/tasks.md",
    ]
    assert git(repo, "status", "--porcelain").split() == ["M", "src/main.py"]
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_the_gate_sees_only_the_pathspecs_staged(repo: Path) -> None:
    edit(repo)
    seen: list[str] = []

    def gate(cwd: Path) -> str:
        seen.extend(git(cwd, "diff", "--cached", "--name-only").split())
        return ""

    build_commit(only=("openspec",), gate=gate)("docs: plan", cwd=repo)

    assert sorted(seen) == [
        "openspec/changes/feature/design.md",
        "openspec/changes/feature/tasks.md",
    ]


def test_a_gate_rejection_commits_nothing_and_stages_only_the_pathspecs(repo: Path) -> None:
    edit(repo)
    before = git(repo, "rev-parse", "HEAD")

    def gate(cwd: Path) -> str:
        return "rejected"

    with pytest.raises(CommitRejected, match="rejected"):
        build_commit(only=("openspec",), gate=gate)("docs: plan", cwd=repo)

    assert git(repo, "rev-parse", "HEAD") == before
    assert "src/main.py" not in git(repo, "diff", "--cached", "--name-only").split()


def test_only_a_file_outside_the_pathspecs_is_nothing_to_commit(repo: Path) -> None:
    (repo / "src/main.py").write_text("edited\n")
    before = git(repo, "rev-parse", "HEAD")

    made = build_commit(only=("openspec", "abk.yaml"))("docs: plan", cwd=repo)

    assert made == 0
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "status", "--porcelain").split() == ["M", "src/main.py"]


def test_the_lock_cleanup_still_runs_with_only(repo: Path, tmp_path: Path) -> None:
    (repo / "openspec/changes/feature/tasks.md").write_text("edited\n")
    (repo / LOCK).write_text("reformatted by a newer tool\n")
    (repo / "src/main.py").write_text("edited\n")
    env = FakeEnvironment(tmp_path / "control", inputs=("manifest.toml",), locks=(LOCK,))
    config = repo_config(tmp_path / "meta", env)

    made = build_commit(repo=config, base="main", only=("openspec",))("docs: plan", cwd=repo)

    assert made == 1
    assert committed(repo) == ["openspec/changes/feature/tasks.md"]
    assert (repo / LOCK).read_text() == "as committed\n"
    assert git(repo, "status", "--porcelain").split() == ["M", "src/main.py"]


def test_without_only_everything_is_staged_and_committed(repo: Path) -> None:
    edit(repo)

    made = build_commit()("msg", cwd=repo)

    assert made == 1
    assert committed(repo) == ALL_EDITED
    assert git(repo, "status", "--porcelain") == ""


def test_a_unit_commit_without_only_stages_everything(repo: Path) -> None:
    edit(repo)

    made = build_commit(unit_id="feature/1")("msg", cwd=repo)

    assert made == 1
    assert committed(repo) == ALL_EDITED
    assert git(repo, "status", "--porcelain") == ""
    assert "Unit: feature/1" in git(repo, "log", "-1", "--format=%B")


def test_a_file_already_staged_outside_the_pathspecs_is_not_committed(repo: Path) -> None:
    (repo / "src/main.py").write_text("edited\n")
    git(repo, "add", "src/main.py")
    (repo / "openspec/changes/feature/tasks.md").write_text("edited\n")

    made = build_commit(only=("openspec",))("docs: plan", cwd=repo)

    assert made == 1
    assert committed(repo) == ["openspec/changes/feature/tasks.md"]
    assert git(repo, "diff", "HEAD", "--name-only").split() == ["src/main.py"]
    assert git(repo, "diff", "--cached", "--name-only").split() == ["src/main.py"]


def test_only_a_file_staged_outside_the_pathspecs_is_nothing_to_commit(repo: Path) -> None:
    (repo / "src/main.py").write_text("edited\n")
    git(repo, "add", "src/main.py")
    before = git(repo, "rev-parse", "HEAD")

    made = build_commit(only=("openspec",))("docs: plan", cwd=repo)

    assert made == 0
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "diff", "--cached", "--name-only").split() == ["src/main.py"]


def test_a_rename_under_the_pathspecs_commits_the_deletion_and_the_addition(repo: Path) -> None:
    old, new = "openspec/changes/feature/tasks.md", "openspec/changes/feature/notes/tasks.md"
    (repo / "openspec/changes/feature/notes").mkdir()
    (repo / old).rename(repo / new)

    made = build_commit(only=("openspec",))("docs: plan", cwd=repo)

    assert made == 1
    shown = git(repo, "show", "--name-status", "--no-renames", "--format=", "HEAD")
    assert sorted(line.split() for line in shown.splitlines()) == [["A", new], ["D", old]]
    assert "openspec" not in git(repo, "status", "--porcelain")
