"""After a restack the generated files are rebuilt from the moved sources and committed.

Real git in temporary repositories; the regenerate command is a small shell script that
appends a line to a log each time it runs, so how often and where it ran is read from the log.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from agent_build_kit.config import GeneratedConfig, RepoConfig
from agent_build_kit.pipeline.generated import GeneratedFilesFailed, regenerate
from agent_build_kit.pipeline.restack import move_branch_onto, resolved_move
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD
from agent_build_kit.pipeline.wiring import build_restack_onto
from tests.factories import commit_files, git, init_repo, unit
from tests.pipeline.test_restack_onto_before_push import BASE, BRANCH, Repos, Resolver, stack

SUBJECT = "chore: Rebuild the generated files after restacking onto main"


def rebuilding(
    log: Path, *, paths: tuple[str, ...], writes: str, cwd: str = "."
) -> GeneratedConfig:
    """An entry whose command logs where it ran, then writes `writes` (relative to its cwd)."""
    script = f'echo "ran in $(pwd)" >> "{log}"; printf "rebuilt\\n" > {writes}'
    return GeneratedConfig(paths=paths, command=("sh", "-c", script), cwd=cwd)


def failing(log: Path, *, paths: tuple[str, ...]) -> GeneratedConfig:
    script = f'echo "ran" >> "{log}"; echo "bundler exploded" >&2; exit 1'
    return GeneratedConfig(paths=paths, command=("sh", "-c", script))


def runs(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def restacked(tmp_path: Path, *, unit_files: dict[str, str]) -> Path:
    """A repository whose `spec/c/2` sits on `main`'s first commit, one commit of the
    unit's `unit_files` ahead, and whose `main` has since moved on."""
    repo = init_repo(tmp_path / "repo")
    commit_files(repo, "start", {"src/app.py": "v = 0\n", "web/out/bundle.js": "start\n"})
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    commit_files(repo, "the unit's work", unit_files)
    git(repo, "checkout", "-q", "main")
    commit_files(repo, "the base moves", {"base.txt": "base\n"})
    git(repo, "checkout", "-q", "spec/c/2")
    git(repo, "rebase", "-q", "main")
    return repo


def subjects(repo: Path, onto: str = "main") -> list[str]:
    return git(repo, "log", "--format=%s", f"{onto}..HEAD").splitlines()


def test_a_unit_touching_a_generated_path_rebuilds_once_in_the_entrys_cwd(tmp_path: Path) -> None:
    repo = restacked(tmp_path, unit_files={"web/out/bundle.js": "edited\n"})
    log = tmp_path / "log"
    entry = rebuilding(log, paths=("web/out/**",), writes="out/bundle.js", cwd="web")

    regenerate(repo, [entry], onto="main")

    assert runs(log) == [f"ran in {(repo / 'web').resolve()}"]
    assert (repo / "web/out/bundle.js").read_text() == "rebuilt\n"


def test_the_rebuilt_files_are_committed_as_one_chore_commit(tmp_path: Path) -> None:
    repo = restacked(tmp_path, unit_files={"web/out/bundle.js": "edited\n"})
    entry = rebuilding(tmp_path / "log", paths=("web/out/**",), writes="web/out/bundle.js")

    regenerate(repo, [entry], onto="main")

    assert subjects(repo) == [SUBJECT, "the unit's work"]
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "show", "HEAD:web/out/bundle.js") == "rebuilt"


def test_no_commit_is_added_when_the_rebuilt_output_is_unchanged(tmp_path: Path) -> None:
    repo = restacked(tmp_path, unit_files={"web/out/bundle.js": "rebuilt\n"})
    log = tmp_path / "log"
    entry = rebuilding(log, paths=("web/out/**",), writes="web/out/bundle.js")

    regenerate(repo, [entry], onto="main")

    assert len(runs(log)) == 1, "the command ran, and found nothing to change"
    assert subjects(repo) == ["the unit's work"]


def test_a_unit_touching_no_generated_path_does_not_run_the_command(tmp_path: Path) -> None:
    repo = restacked(tmp_path, unit_files={"src/app.py": "v = 1\n"})
    log = tmp_path / "log"
    entry = rebuilding(log, paths=("web/out/**",), writes="web/out/bundle.js")

    regenerate(repo, [entry], onto="main")

    assert runs(log) == []
    assert subjects(repo) == ["the unit's work"]


def test_a_failing_command_raises_with_its_output(tmp_path: Path) -> None:
    repo = restacked(tmp_path, unit_files={"web/out/bundle.js": "edited\n"})

    with pytest.raises(GeneratedFilesFailed) as raised:
        regenerate(repo, [failing(tmp_path / "log", paths=("web/out/**",))], onto="main")

    assert "bundler exploded" in raised.value.output
    assert subjects(repo) == ["the unit's work"]


def test_a_failed_regeneration_is_held_under_its_own_cause(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=False)
    entry = failing(tmp_path / "log", paths=("marker.py",))
    config = RepoConfig(path=repos.tree, generated=[entry])

    with contextlib.suppress(GeneratedFilesFailed):
        build_restack_onto(store, repo=config)(
            tree=repos.tree, branch=BRANCH, base=BASE, unit=unit(), resolve=False
        )

    held = store.get(unit().id)
    assert (held.state, held.cause) == (HELD, Cause.GENERATED_FILES)
    assert "bundler exploded" in held.note


# The three restack paths each rebuild the generated files exactly once. A unit that adds
# `marker.py` touches it; the entry declares it generated.
def marker_entry(log: Path) -> GeneratedConfig:
    return rebuilding(log, paths=("marker.py",), writes="marker.py")


def test_a_plain_restack_rebuilds_once(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    old_base = git(repos.tree, "rev-parse", BASE)
    repos.advance_trunk(conflicting=False)
    log = tmp_path / "log"
    config = RepoConfig(path=repos.tree, generated=[marker_entry(log)])

    move_branch_onto(repos.tree, BRANCH, new_base=BASE, old_base=old_base, repo_config=config)

    assert len(runs(log)) == 1
    assert git(repos.tree, "log", "-1", "--format=%s").startswith("chore: Rebuild the generated")


def test_the_build_workers_moved_base_restack_rebuilds_once(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=False)
    log = tmp_path / "log"
    config = RepoConfig(path=repos.tree, generated=[marker_entry(log)])

    moved = build_restack_onto(store, repo=config)(
        tree=repos.tree, branch=BRANCH, base=BASE, unit=unit(), resolve=False
    )

    assert moved is not None
    assert len(runs(log)) == 1
    assert git(repos.tree, "log", "-1", "--format=%s").startswith("chore: Rebuild the generated")


def test_the_resolution_lane_restack_rebuilds_once(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    old_base = git(repos.tree, "rev-parse", BASE)
    repos.advance_trunk(conflicting=False)
    log = tmp_path / "log"
    config = RepoConfig(path=repos.tree, generated=[marker_entry(log)])

    resolved_move(
        repos.tree,
        BRANCH,
        new_base=BASE,
        old_base=old_base,
        moving_unit="feature/2",
        moving_intent="add the marker",
        onto_unit="feature/1",
        onto_intent="move the trunk",
        resolve=Resolver(),
        repo_config=config,
    )

    assert len(runs(log)) == 1
    assert git(repos.tree, "log", "-1", "--format=%s").startswith("chore: Rebuild the generated")
