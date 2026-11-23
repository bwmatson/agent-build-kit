"""The repository's own hooks and CI leave spec-and-state commits alone: the state
directory skips the file-editing and size hooks, `abk.yaml` is still linted, and
the test jobs run only when something outside the planning paths changed."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from tests import tracked_files
from tests.factories import git, init_repo

ROOT = Path(__file__).parent.parent
SCOPE_SCRIPT = ROOT / "scripts" / "ci_scope.py"
EDITING_HOOKS = ("trailing-whitespace", "end-of-file-fixer", "check-added-large-files")
STATE_FILE = "runs/units.json"


def pre_commit() -> dict:
    return yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())


def hook(config: dict, hook_id: str) -> dict:
    return next(h for repo in config["repos"] for h in repo["hooks"] if h["id"] == hook_id)


def skips(config: dict, hook_id: str, path: str) -> bool:
    """Whether `hook_id` never reads `path`: the top-level exclude or its own covers it."""
    patterns = (config.get("exclude"), hook(config, hook_id).get("exclude"))
    return any(re.search(pattern, path) for pattern in patterns if pattern)


def reads(config: dict, hook_id: str, path: str) -> bool:
    """Whether `hook_id` runs for a change to `path`: its `files` pattern matches and no
    exclude skips it."""
    pattern = hook(config, hook_id).get("files")
    return (pattern is None or re.search(pattern, path) is not None) and not skips(
        config, hook_id, path
    )


def pyrefly_includes() -> list[str]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pyrefly"][
        "project-includes"
    ]


def workflow() -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())


@pytest.mark.parametrize("hook_id", EDITING_HOOKS)
def test_the_state_directory_is_skipped_by_the_editing_and_size_hooks(hook_id: str) -> None:
    assert skips(pre_commit(), hook_id, STATE_FILE)
    assert not skips(pre_commit(), hook_id, "src/agent_build_kit/__init__.py")


def test_the_large_file_hook_keeps_skipping_the_lock_beside_the_state_directory() -> None:
    config = pre_commit()

    assert skips(config, "check-added-large-files", "uv.lock")
    assert skips(config, "check-added-large-files", STATE_FILE)


def test_yamllint_is_strict_and_reads_abk_yaml_while_the_state_directory_is_skipped() -> None:
    config = pre_commit()

    assert "--strict" in hook(config, "yamllint")["args"]
    assert not skips(config, "yamllint", "abk.yaml")
    assert skips(config, "yamllint", STATE_FILE)


@pytest.mark.parametrize(
    "path",
    [
        "src/agent_build_kit/__init__.py",
        "packages/core/src/agent_build_kit/model.py",
        "packages/worker/src/agent_build_kit/graph/nodes.py",
    ],
)
def test_the_type_check_hook_runs_for_a_change_in_any_package(path: str) -> None:
    assert reads(pre_commit(), "pyrefly-check", path)


def test_the_type_check_project_covers_every_source_and_test_tree() -> None:
    includes = pyrefly_includes()
    # `test_tree_folders` is a helper, not a test: reached through the module, pytest skips it.
    trees = [*tracked_files.source_tree_folders(), *tracked_files.test_tree_folders()]

    uncovered = [
        tree
        for tree in trees
        if not any(tree == include or tree.startswith(f"{include}/") for include in includes)
    ]

    assert uncovered == [], f"pyrefly's project-includes leaves out {uncovered}"


def test_a_scope_job_gates_the_test_and_integration_jobs_on_its_code_output() -> None:
    jobs = workflow()["jobs"]

    assert "scope" in jobs
    assert "code" in jobs["scope"]["outputs"]
    for name in ("test", "integration"):
        assert "scope" in jobs[name]["needs"]
        assert "needs.scope.outputs.code" in jobs[name]["if"]


def test_the_hook_job_always_runs_and_the_workflow_has_no_path_filter() -> None:
    ci = workflow()
    triggers = ci.get("on", ci.get(True))

    assert "scope" in ci["jobs"], "the scope job is what the other two wait for"
    assert "if" not in ci["jobs"]["pre-commit"]
    assert "scope" not in ci["jobs"]["pre-commit"].get("needs", [])
    for event in ("pull_request", "push"):
        assert not {"paths", "paths-ignore"} & set(triggers[event] or ())


def scope_output(tmp_path: Path, *paths: str, moves: dict[str, str] | None = None) -> str:
    """What the scope script prints for a commit that touches `paths`, and moves each
    file of `moves` (a path in the first commit) to its value, in a new repository."""
    repo = init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("start\n")
    for source in moves or {}:
        (repo / source).parent.mkdir(parents=True, exist_ok=True)
        (repo / source).write_text("content that survives a move\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD").strip()
    for source, destination in (moves or {}).items():
        (repo / destination).parent.mkdir(parents=True, exist_ok=True)
        git(repo, "mv", source, destination)
    for path in paths:
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text("changed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "head")
    head = git(repo, "rev-parse", "HEAD").strip()
    done = subprocess.run(
        [sys.executable, "-I", str(SCOPE_SCRIPT), base, head],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.mark.parametrize(
    "paths",
    [
        ("openspec/changes/feature/tasks.md",),
        ("runs/units.json",),
        ("docs/unit_graph.md", "docs/unit_cost.md"),
        ("openspec/specs/x/spec.md", "runs/units.json", "docs/unit_graph.md"),
        ("abk.yaml",),
    ],
)
def test_only_planning_paths_changed_is_no_code_change(
    tmp_path: Path, paths: tuple[str, ...]
) -> None:
    assert scope_output(tmp_path, *paths) == "code=false"


@pytest.mark.parametrize(
    "paths",
    [
        ("src/agent_build_kit/__init__.py",),
        ("docs/architecture.md",),
        ("openspec/changes/feature/tasks.md", "pyproject.toml"),
        ("abk.yaml", "tests/test_x.py"),
    ],
)
def test_any_other_path_changed_is_a_code_change(tmp_path: Path, paths: tuple[str, ...]) -> None:
    assert scope_output(tmp_path, *paths) == "code=true"


@pytest.mark.parametrize(
    "source, destination",
    [
        ("src/agent_build_kit/foo.py", "openspec/foo.py"),
        ("tests/test_foo.py", "runs/test_foo.py"),
    ],
)
def test_a_code_file_moved_into_a_planning_path_is_a_code_change(
    tmp_path: Path, source: str, destination: str
) -> None:
    assert scope_output(tmp_path, moves={source: destination}) == "code=true"
