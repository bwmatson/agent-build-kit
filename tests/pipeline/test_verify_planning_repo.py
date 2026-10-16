"""Verify of a repo whose checkout is the planning root, run in the pipeline worktree."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.verify import Verification, verify_change
from tests.conftest import make_installation
from tests.factories import commit_files, git, init_repo, stored_unit
from tests.planning_worktree_support import InRepo, in_repo, publish_elsewhere

TRACKED = {
    "src/main.py": "print('app')\n",
    "tests/integration/test_live.py": "def test_live(): ...\n",
    "abk.yaml": "repos: {}\n",
    "notes/learned.md": "notes\n",
    "docs/unit_graph.md": "graph\n",
    "docs/unit_cost.md": "cost\n",
    "openspec/changes/feature/tasks.md": "- [ ] 1.1 Do it\n",
    "openspec/changes/feature/proposal.md": "why\n",
}


class Host:
    """Runs git for real and records every command with where it ran; a command that is not git,
    and `git pull`, are recorded and succeed without running."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def __call__(self, command, **kwargs) -> subprocess.CompletedProcess:
        argv = tuple(command)
        cwd = Path(kwargs["cwd"])
        self.calls.append((argv, cwd))
        if argv[0] != "git" or argv[1] == "pull":
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)

    def deploys(self) -> list[Path]:
        return [cwd for argv, cwd in self.calls if argv[0] == "deploy"]

    def live_tests(self) -> list[Path]:
        return [cwd for argv, cwd in self.calls if "pytest" in argv]

    def pulls(self) -> list[Path]:
        return [cwd for argv, cwd in self.calls if argv[:2] == ("git", "pull")]


def pipeline_worktree(base: Path) -> InRepo:
    """The pipeline worktree of `app`, detached at the tip of `main`, holding `TRACKED`."""
    setup = in_repo(base)
    publish_elsewhere(setup, TRACKED, "add planning and code")
    git(setup.worktree, "fetch", "-q", "origin")
    git(setup.worktree, "checkout", "-q", "--detach", "origin/main")
    return setup


def installation(setup: InRepo, planning: dict | None = None, **extra_repos) -> Installation:
    repos = {
        "app": {
            "path": str(setup.working_copy),
            "slug": "example/app",
            "deploy": {"rules": [{"prefix": "src/", "run": [["deploy", "app"]]}]}
            | {"live_written": ["notes/"]},
        },
        **extra_repos,
    }
    return make_installation(setup.worktree, repos=repos, planning=planning or {})


def verify(
    inst: Installation, host: Host, *repos: str, files: tuple[str, ...] = ("src/main.py",)
) -> Verification:
    units = [
        stored_unit(f"feature/{n}", change="feature", repo=repo, state="merged", pr=n)
        for n, repo in enumerate(repos or ("app",), 1)
    ]
    return verify_change(
        "feature",
        units,
        installation=inst,
        pr_files=lambda name, pr: list(files),
        run=host,
        env={},
    )


def touch_planning_paths(tree: Path) -> None:
    (tree / "runs" / "units.json").write_text('["state"]\n')
    (tree / "docs" / "unit_graph.md").write_text("graph, changed\n")
    (tree / "docs" / "unit_cost.md").write_text("cost, changed\n")
    (tree / "openspec" / "changes" / "feature" / "tasks.md").write_text("- [x] 1.1 Do it\n")
    git(tree, "mv", "openspec/changes/feature/proposal.md", "openspec/changes/archived.md")


def test_modified_planning_paths_do_not_hold_up_verification(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)
    touch_planning_paths(setup.worktree)
    host = Host()

    result = verify(installation(setup), host)

    assert result.passed, result.detail
    assert host.deploys()


def test_a_modified_source_file_refuses_naming_only_that_file(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)
    touch_planning_paths(setup.worktree)
    (setup.worktree / "src" / "main.py").write_text("print('edited')\n")
    host = Host()

    result = verify(installation(setup), host)

    assert not result.passed
    assert "src/main.py" in result.detail
    for exempt in ("units.json", "unit_graph.md", "unit_cost.md", "tasks.md", "archived.md"):
        assert exempt not in result.detail
    assert not host.deploys()


def test_a_modified_abk_yaml_refuses(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)
    (setup.worktree / "abk.yaml").write_text("repos: {changed: true}\n")
    host = Host()

    result = verify(installation(setup), host)

    assert not result.passed
    assert "abk.yaml" in result.detail
    assert not host.deploys()


def test_paths_the_system_writes_are_still_excluded(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)
    (setup.worktree / "notes" / "learned.md").write_text("learned\n")

    result = verify(installation(setup), Host())

    assert result.passed, result.detail


def test_a_worktree_behind_the_tip_fails_naming_the_commits_it_lacks(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)
    publish_elsewhere(setup, {"later.txt": "later\n"}, "a commit it lacks")
    git(setup.worktree, "fetch", "-q", "origin")
    host = Host()

    result = verify(installation(setup), host)

    assert not result.passed
    assert "a commit it lacks" in result.detail
    assert not host.deploys()


def test_the_pull_is_replaced_by_the_sync(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)
    host = Host()

    result = verify(installation(setup), host)

    assert result.passed, result.detail
    assert host.pulls() == []


def test_a_stopped_sync_fails_verification_with_its_reason_and_deploys_nothing(
    tmp_path: Path,
) -> None:
    setup = pipeline_worktree(tmp_path)
    git(setup.worktree, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    host = Host()

    result = verify(installation(setup), host)

    assert not result.passed
    assert "gone.git" in result.detail
    assert not host.deploys()


def test_deploy_commands_run_in_the_root(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)
    host = Host()

    verify(installation(setup), host)

    assert host.deploys() == [setup.worktree]


def test_live_tests_run_in_the_root(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)
    host = Host()

    result = verify(installation(setup), host, files=("tests/integration/test_live.py",))

    assert result.passed, result.detail
    assert host.live_tests() == [setup.worktree]


def test_a_planning_path_outside_the_root_does_not_make_a_dirty_tree_read_clean(
    tmp_path: Path,
) -> None:
    setup = pipeline_worktree(tmp_path)
    (setup.worktree / "src" / "main.py").write_text("print('edited')\n")
    outside = tmp_path / "elsewhere" / "state"
    host = Host()

    result = verify(installation(setup, planning={"state_dir": str(outside)}), host)

    assert not result.passed
    assert "src/main.py" in result.detail
    assert not host.deploys()


def test_a_sync_that_did_not_update_is_said_in_the_detail(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)

    result = verify(installation(setup, planning={"self_pull": False}), Host())

    assert result.passed, result.detail
    assert "self_pull" in result.detail


def platform_repo(base: Path) -> dict:
    path = init_repo(base / "platform")
    commit_files(path, "start", {"runs/units.json": "[]\n", "svc/main.py": "x\n"})
    return {
        "path": str(path),
        "slug": "example/platform",
        "deploy": {"rules": [{"prefix": "src/", "run": [["deploy", "platform"]]}]},
    }


def test_another_repo_keeps_its_branch_test_its_dirty_test_and_its_pull(tmp_path: Path) -> None:
    setup = pipeline_worktree(tmp_path)
    platform = platform_repo(tmp_path)
    inst = installation(setup, platform=platform)
    where = Path(platform["path"])

    # the planning root's repo passes detached, beside a repo that is checked as before
    host = Host()
    both = verify(inst, host, "app", "platform")
    assert both.passed, both.detail
    assert host.pulls() == [where]
    assert sorted(host.deploys()) == sorted([where, setup.worktree])

    # a planning path is only exempt for the planning root's repo
    (where / "runs" / "units.json").write_text('["state"]\n')
    host = Host()
    dirty = verify(inst, host, "app", "platform")
    assert not dirty.passed
    assert "runs/units.json" in dirty.detail
    assert not host.deploys()

    # a detached HEAD at the tip is still not the default branch
    git(where, "checkout", "-q", "--", "runs/units.json")
    git(where, "checkout", "-q", "--detach")
    host = Host()
    detached = verify(inst, host, "app", "platform")
    assert not detached.passed
    assert "not on main" in detached.detail
    assert host.pulls() == []
