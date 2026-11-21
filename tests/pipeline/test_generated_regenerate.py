"""After a restack the generated files are rebuilt from the moved sources and committed.

Real git in temporary repositories; the regenerate command is a small shell script that
appends a line to a log each time it runs, so how often and where it ran is read from the log.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import GeneratedConfig, RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.generated import GeneratedFilesFailed, regenerate
from agent_build_kit.pipeline.restack import move_branch_onto, resolved_move
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD
from agent_build_kit.pipeline.wiring import build_restack_onto
from packages.worker.tests.graph.test_build_path import build
from packages.worker.tests.graph.test_remaining_paths import fresh
from tests.factories import commit_files, git, init_repo, unit
from tests.pipeline.test_events_restack_scope import restacking
from tests.pipeline.test_flake_fix_change import code_repo
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


def test_the_build_workers_restack_lets_a_failed_rebuild_reach_its_caller(tmp_path: Path) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    store = stack(tmp_path)
    repos.advance_trunk(conflicting=False)
    config = RepoConfig(
        path=repos.tree, generated=[failing(tmp_path / "log", paths=("marker.py",))]
    )

    with pytest.raises(GeneratedFilesFailed, match="bundler exploded"):
        build_restack_onto(store, repo=config)(
            tree=repos.tree, branch=BRANCH, base=BASE, unit=unit(), resolve=False
        )


def test_a_failed_rebuild_in_the_prepare_step_ends_the_unit_held_not_failed(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)

    def rebuild_fails(**kw: Any) -> None:
        raise GeneratedFilesFailed("bundler exploded")

    outcome = build(
        tmp_path,
        recorder,
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=rebuild_fails,
    )

    stored = recorder.store.get(unit().id)
    assert outcome.status == "held"
    assert (stored.state, stored.cause) == (HELD, Cause.GENERATED_FILES)
    assert "bundler exploded" in stored.note
    assert "push" not in recorder.events and "pr" not in recorder.events


def test_a_failed_rebuild_in_the_merge_handlers_restack_holds_the_unit(
    installation: Installation,
) -> None:
    code_repo(installation)
    store, _, pushed, run = restacking(installation, GeneratedFilesFailed("bundler exploded"))

    run()

    held = store.get("feature/1")
    assert (held.state, held.cause) == (HELD, Cause.GENERATED_FILES)
    assert "bundler exploded" in held.note
    assert pushed == []


def started_at(repos: Repos) -> str:
    return git(repos.tree, "rev-parse", BRANCH)


def test_a_failed_rebuild_puts_the_branch_back_and_the_next_move_rebuilds(
    tmp_path: Path,
) -> None:
    repos = Repos(tmp_path, edits_shared=False)
    old_base = git(repos.tree, "rev-parse", BASE)
    repos.advance_trunk(conflicting=False)
    before = started_at(repos)
    script = 'echo "half" > marker.py; echo "bundler exploded" >&2; exit 1'
    broken = GeneratedConfig(paths=("marker.py",), command=("sh", "-c", script))

    with pytest.raises(GeneratedFilesFailed, match="bundler exploded"):
        move_branch_onto(
            repos.tree,
            BRANCH,
            new_base=BASE,
            old_base=old_base,
            repo_config=RepoConfig(path=repos.tree, generated=[broken]),
        )

    assert started_at(repos) == before
    assert git(repos.tree, "status", "--porcelain") == ""

    log = tmp_path / "log"
    move_branch_onto(
        repos.tree,
        BRANCH,
        new_base=BASE,
        old_base=old_base,
        repo_config=RepoConfig(path=repos.tree, generated=[marker_entry(log)]),
    )

    assert len(runs(log)) == 1
    assert git(repos.tree, "log", "-1", "--format=%s").startswith("chore: Rebuild the generated")


def test_a_bare_file_name_pattern_matches_the_file_anywhere(tmp_path: Path) -> None:
    repo = restacked(tmp_path, unit_files={"web/out/bundle.js": "edited\n"})
    log = tmp_path / "log"
    entry = rebuilding(log, paths=("bundle.js",), writes="web/out/bundle.js")

    regenerate(repo, [entry], onto="main")

    assert len(runs(log)) == 1


def test_only_changes_under_the_entrys_paths_are_committed(tmp_path: Path) -> None:
    repo = restacked(tmp_path, unit_files={"web/out/bundle.js": "edited\n"})
    script = 'printf "x\\n" > web/out/bundle.js; printf "cache\\n" > web/cache.txt'
    entry = GeneratedConfig(paths=("web/out/**",), command=("sh", "-c", script))

    regenerate(repo, [entry], onto="main")

    assert git(repo, "show", "--name-only", "--format=", "HEAD") == "web/out/bundle.js"
    assert git(repo, "status", "--porcelain") == "?? web/cache.txt"


def test_a_command_that_is_not_installed_raises_naming_it(tmp_path: Path) -> None:
    repo = restacked(tmp_path, unit_files={"web/out/bundle.js": "edited\n"})
    entry = GeneratedConfig(paths=("web/out/**",), command=("no-such-bundler-here", "build"))

    with pytest.raises(GeneratedFilesFailed, match="no-such-bundler-here build"):
        regenerate(repo, [entry], onto="main")


def test_a_command_running_past_the_timeout_raises(tmp_path: Path) -> None:
    repo = restacked(tmp_path, unit_files={"web/out/bundle.js": "edited\n"})
    entry = GeneratedConfig(paths=("web/out/**",), command=("sleep", "60"))

    with pytest.raises(GeneratedFilesFailed, match="timed out"):
        regenerate(repo, [entry], onto="main", timeout=0.05)


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
