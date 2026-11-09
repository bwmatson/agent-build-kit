"""A small real git project whose `main` is the base the selection data is recorded on (spec:
selection-data-comes-from-the-base)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.shell import git, git_out


class BaseRepo:
    """A repository with a `tests/` folder and a project file, whose `main` moves on `move()`."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        repo.mkdir(parents=True)
        git(repo, "init", "-b", "main")
        git(repo, "config", "user.email", "a@example.com")
        git(repo, "config", "user.name", "a")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
        (repo / "pyproject.toml").write_text('[project]\nname = "x"\n')
        self.move()

    def tip(self) -> str:
        return git_out(self.repo, "rev-parse", "main").strip()

    def move(self) -> str:
        """A new commit on the base; its hash."""
        marker = self.repo / "marker.txt"
        marker.write_text(marker.read_text() + "x" if marker.exists() else "x")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "move")
        return self.tip()
