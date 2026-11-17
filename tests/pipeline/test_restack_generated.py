"""A restack settles conflicts in generated files from the base, without a resolver.

A repository that declares `generated` output has no one to ask about a bundle that
both sides rebuilt: the base's files are taken (or removed, where the base has none)
and only the source conflicts reach the resolver. A conflicted path that is not in
the working tree, as one both sides deleted is not, never crashes building the conflict.
"""

from pathlib import Path

import pytest

from agent_build_kit.config import GeneratedConfig, RepoConfig
from agent_build_kit.pipeline.restack import (
    ConflictContext,
    RestackConflict,
    move_branch_onto,
    partition_generated,
)
from tests.factories import commit_files, git, init_repo

GENERATED = GeneratedConfig(paths=("assets/**",), command=("true",))


def context() -> ConflictContext:
    return ConflictContext(
        moving_unit="feature/2",
        moving_intent="Rebuild the bundle and edit the source",
        onto_unit="feature/1",
        onto_intent="Rebuild the bundle too",
    )


class Resolver:
    """A stand-in resolver that records what it is asked and writes `answers`."""

    def __init__(self, answers: dict[str, str] | None = None) -> None:
        self.answers = answers or {}
        self.prompts: list[str] = []

    def __call__(self, prompt: str, *, cwd: Path, follow_up: str = "") -> None:
        self.prompts.append(prompt)
        for name, content in self.answers.items():
            (cwd / name).write_text(content)


def stacked(tmp_path: Path, *, unit: dict[str, str | None], base: dict[str, str | None]) -> Path:
    """A repository whose `main` and `spec/c/2` each changed the assets as given
    (None deletes the file), both starting from the same commit `spec/c/1`."""
    repo = init_repo(tmp_path / "repo")
    commit_files(
        repo,
        "start",
        {
            "src/app.py": "value = 0\n",
            "assets/app-1.js": "one\n",
            "assets/both-deleted.js": "gone\n",
            "assets/both-modified.js": "start\n",
            "assets/base-deleted.js": "start\n",
            "assets/unit-deleted.js": "start\n",
        },
    )
    git(repo, "checkout", "-q", "-b", "spec/c/1")
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    change(repo, "the unit rebuilt the bundle", unit)
    git(repo, "checkout", "-q", "main")
    change(repo, "the base rebuilt the bundle", base)
    return repo


def change(repo: Path, message: str, files: dict[str, str | None]) -> None:
    for name, content in files.items():
        if content is None:
            git(repo, "rm", "-q", name)
    commit_files(repo, message, {name: text for name, text in files.items() if text is not None})


def rebuilt_on_both_sides() -> tuple[dict[str, str | None], dict[str, str | None]]:
    """What a unit and a base each did to the bundle, so every conflict kind occurs."""
    unit: dict[str, str | None] = {
        "assets/app-1.js": None,
        "assets/app-2.js": "unit\n",
        "assets/both-deleted.js": None,
        "assets/both-modified.js": "unit\n",
        "assets/base-deleted.js": "unit\n",
        "assets/unit-deleted.js": None,
        "assets/both-added.js": "unit\n",
    }
    base: dict[str, str | None] = {
        "assets/app-1.js": None,
        "assets/app-3.js": "base\n",
        "assets/both-deleted.js": None,
        "assets/both-modified.js": "base\n",
        "assets/base-deleted.js": None,
        "assets/unit-deleted.js": "base\n",
        "assets/both-added.js": "base\n",
    }
    return unit, base


def moved(repo: Path, resolver: Resolver, config: RepoConfig) -> RestackConflict | None:
    """Move `spec/c/2` onto `main`; the conflict that was left for a human, if any."""
    try:
        move_branch_onto(
            repo,
            "spec/c/2",
            new_base="main",
            old_base="spec/c/1",
            resolve=resolver,
            context=context(),
            repo_config=config,
        )
    except RestackConflict as conflict:
        return conflict
    return None


def show(repo: Path, path: str) -> str | None:
    """The file at the moved branch's tip (no trailing newline), None when it is not there."""
    listed = git(repo, "ls-tree", "--name-only", "spec/c/2", "--", path)
    return git(repo, "show", f"spec/c/2:{path}").rstrip("\n") if listed.strip() else None


def test_assets_changed_on_both_sides_restack_onto_the_base_without_the_resolver(
    tmp_path: Path,
) -> None:
    unit, base = rebuilt_on_both_sides()
    repo = stacked(tmp_path, unit=unit, base=base)
    resolver = Resolver()

    left = moved(repo, resolver, RepoConfig(path=repo, generated=[GENERATED]))

    assert left is None
    assert resolver.prompts == []
    assert show(repo, "assets/both-modified.js") == "base"
    assert show(repo, "assets/unit-deleted.js") == "base"
    assert show(repo, "assets/both-added.js") == "base"
    assert show(repo, "assets/app-3.js") == "base"
    assert show(repo, "assets/base-deleted.js") is None
    assert show(repo, "assets/both-deleted.js") is None
    assert show(repo, "assets/app-1.js") is None
    assert not (repo / ".git" / "rebase-merge").exists()


def test_a_source_conflict_beside_generated_ones_reaches_the_resolver_alone(
    tmp_path: Path,
) -> None:
    unit, base = rebuilt_on_both_sides()
    unit["src/app.py"] = "value = 1\n"
    base["src/app.py"] = "value = 2\n"
    repo = stacked(tmp_path, unit=unit, base=base)
    resolver = Resolver({"src/app.py": "value = 3\n"})

    left = moved(repo, resolver, RepoConfig(path=repo, generated=[GENERATED]))

    assert left is None
    (prompt,) = resolver.prompts
    assert "- src/app.py" in prompt
    assert "- assets/both-modified.js" not in prompt
    assert "assets/both-modified.js" in prompt  # named as taken from the base
    assert show(repo, "src/app.py") == "value = 3"
    assert show(repo, "assets/both-modified.js") == "base"


def test_a_conflicted_path_absent_from_the_working_tree_does_not_raise(tmp_path: Path) -> None:
    """Both sides renamed a file, so the original path is conflicted and not on disk."""
    repo = init_repo(tmp_path / "repo")
    commit_files(repo, "start", {"notes.txt": "a\nb\nc\nd\ne\nf\n"})
    git(repo, "checkout", "-q", "-b", "spec/c/1")
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    git(repo, "mv", "notes.txt", "unit-notes.txt")
    git(repo, "commit", "-qm", "the unit renames it")
    git(repo, "checkout", "-q", "main")
    git(repo, "mv", "notes.txt", "base-notes.txt")
    git(repo, "commit", "-qm", "the base renames it")

    # Whether the resolution is accepted is not the subject: reading the conflict must not raise.
    raised: FileNotFoundError | None = None
    try:
        moved(repo, Resolver(), RepoConfig(path=repo))
    except FileNotFoundError as error:
        raised = error
    assert raised is None


@pytest.mark.parametrize(
    ("files", "entries", "generated", "others"),
    [
        (["assets/a.js", "src/app.py"], [GENERATED], ["assets/a.js"], ["src/app.py"]),
        (["src/app.py"], [GENERATED], [], ["src/app.py"]),
        (["assets/a.js"], [GENERATED], ["assets/a.js"], []),
        (["assets/a.js", "src/app.py"], [], [], ["assets/a.js", "src/app.py"]),
    ],
)
def test_conflicted_files_split_by_the_generated_entries(
    files: list[str],
    entries: list[GeneratedConfig],
    generated: list[str],
    others: list[str],
) -> None:
    assert partition_generated(files, entries) == (generated, others)
