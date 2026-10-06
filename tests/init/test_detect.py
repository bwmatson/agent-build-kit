"""What `abk init` reads off a checkout.

Real temporary git repos rather than a fake runner: the questions are about
git's answers (the origin URL, the remote HEAD, tracked files), and a fake
would only restate the test's own assumptions about them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_build_kit.init.detect import (
    DEV_STACK_SCRIPT,
    detect_repo,
    parse_slug,
    resolve_consumes,
)
from tests.factories import git, init_repo


def commit_all(repo: Path, message: str = "init") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:example/app.git",
        "https://github.com/example/app",
        "https://github.com/example/app.git",
        "ssh://git@github.com/example/app.git",
        "github-example:example/app.git",
    ],
)
def test_origin_forms_all_yield_the_slug(url: str) -> None:
    assert parse_slug(url) == "example/app"


def test_a_non_github_looking_url_yields_no_slug() -> None:
    assert parse_slug("/srv/git/app.git") is None
    assert parse_slug("") is None


def test_a_plain_directory_is_not_a_git_repo(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    detection = detect_repo(tmp_path / "app")

    assert not detection.is_git
    assert detection.slug is None
    assert detection.default_branch == "main"
    assert not detection.has_code
    assert detection.name == "app"


def test_slug_and_default_branch_come_from_the_remote(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")

    detection = detect_repo(repo)

    assert detection.slug == "example/app"
    assert detection.default_branch == "develop"


def test_default_branch_falls_back_to_main_without_a_remote_head(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "https://github.com/example/app")

    assert detect_repo(repo).default_branch == "main"


def test_languages_and_profile_from_tooling_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n')
    (repo / "uv.lock").write_text("")
    (repo / "package.json").write_text("{}")
    (repo / "tsconfig.json").write_text("{}")

    detection = detect_repo(repo)

    assert detection.languages == ["python", "javascript", "typescript"]
    assert detection.profile == "python-uv"


@pytest.mark.parametrize("marker", ["compose.yaml", "docker-compose.yml", "Dockerfile"])
def test_a_container_marker_in_the_root_detects_the_docker_infrastructure(
    tmp_path: Path, marker: str
) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / marker).write_text("")

    assert detect_repo(repo).infra == "docker"


def test_a_repo_with_no_container_marker_detects_no_infrastructure(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n')

    assert detect_repo(repo).infra == "none"


def test_a_javascript_only_repo_gets_the_node_profile(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "web")
    (repo / "package.json").write_text("{}")

    detection = detect_repo(repo)

    assert detection.languages == ["javascript"]
    assert detection.profile == "node-npm"


def test_tool_uv_table_counts_as_uv(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "app"\n[tool.uv]\ndev-dependencies = []\n'
    )

    assert detect_repo(repo).profile == "python-uv"


def test_docs_only_repo_has_no_code(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / "README.md").write_text("# app\n")
    (repo / "LICENSE").write_text("MIT\n")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n')
    (repo / "docs").mkdir()
    (repo / "docs" / "plan.md").write_text("plan\n")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    commit_all(repo)

    assert not detect_repo(repo).has_code


def test_a_tracked_source_file_means_code(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n")
    commit_all(repo)

    assert detect_repo(repo).has_code


def test_untracked_source_is_not_code_yet(tmp_path: Path) -> None:
    """The file has to be committed: an empty repo with a stray file in the
    working tree is still an empty repo."""
    repo = init_repo(tmp_path / "app")
    (repo / "README.md").write_text("# app\n")
    commit_all(repo)
    (repo / "app.py").write_text("x = 1\n")

    assert not detect_repo(repo).has_code


def test_service_dirs_are_top_level_dirs_with_a_build_marker(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    for name, marker in (
        ("api", "Dockerfile"),
        ("worker", "pyproject.toml"),
        ("web", "package.json"),
    ):
        (repo / name).mkdir()
        (repo / name / marker).write_text("")
    (repo / "docs").mkdir()
    (repo / "node_modules" / "left-pad").mkdir(parents=True)
    (repo / "node_modules" / "left-pad" / "package.json").write_text("{}")

    assert detect_repo(repo).service_dirs == ["api", "web", "worker"]


def test_dev_stack_script_and_credentials_array(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    script = repo / DEV_STACK_SCRIPT
    script.parent.mkdir()
    script.write_text("#!/bin/bash\nTEST_CREDENTIALS=(\n  API_KEY\n  DB_PASSWORD\n)\n")

    detection = detect_repo(repo)

    assert detection.dev_stack_script == DEV_STACK_SCRIPT
    assert detection.credentials_array == "TEST_CREDENTIALS"


def test_dev_stack_script_without_an_array(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    (repo / "scripts").mkdir()
    (repo / DEV_STACK_SCRIPT).write_text("#!/bin/bash\necho up\n")

    detection = detect_repo(repo)

    assert detection.dev_stack_script == DEV_STACK_SCRIPT
    assert detection.credentials_array is None


def test_consumes_resolves_from_uv_sources_and_package_json(tmp_path: Path) -> None:
    platform = init_repo(tmp_path / "platform")
    git(platform, "remote", "add", "origin", "git@github.com:example/platform.git")
    app = init_repo(tmp_path / "app")
    git(app, "remote", "add", "origin", "git@github.com:example/app.git")
    (app / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["shared"]\n'
        "[tool.uv.sources]\n"
        'shared = { git = "ssh://git@github.com/example/platform.git", rev = "abc" }\n'
    )
    web = init_repo(tmp_path / "web")
    (web / "package.json").write_text(
        json.dumps({"dependencies": {"platform-client": "github:example/platform#v1"}})
    )

    detections = resolve_consumes(
        {name: detect_repo(tmp_path / name) for name in ("platform", "app", "web")}
    )

    assert detections["app"].consumes == ["platform"]
    assert detections["web"].consumes == ["platform"]
    assert detections["platform"].consumes == []


def test_git_failures_go_through_the_injected_runner(tmp_path: Path) -> None:
    """A runner that says git is broken leaves every git-derived field at its
    fallback rather than raising."""
    repo = init_repo(tmp_path / "app")

    def broken(argv, **kwargs):
        raise OSError("no git")

    detection = detect_repo(repo, run=broken)

    assert detection.is_git
    assert detection.slug is None
    assert detection.default_branch == "main"
    assert not detection.has_code


# --- nested projects --------------------------------------------------------------


def test_a_repo_whose_projects_are_nested_reports_both_languages(tmp_path: Path) -> None:
    """The layout a monorepo-ish checkout actually has: nothing at the root, a
    Python project two levels down and its web app one level below that. Reading
    only the root said "no language detected", which left the repo with no
    recommendations document and no proposed changes."""
    repo = init_repo(tmp_path / "accelerators")
    poc = repo / "pipelines" / "poc"
    poc.mkdir(parents=True)
    (poc / "pyproject.toml").write_text('[project]\nname = "poc"\n')
    (poc / "uv.lock").write_text("")
    web = poc / "web"
    web.mkdir()
    (web / "package.json").write_text("{}")
    (web / "tsconfig.json").write_text("{}")

    detection = detect_repo(repo)

    assert detection.languages == ["python", "javascript", "typescript"]
    assert detection.profile == "python-uv"
    assert [
        (project.path, project.languages, project.profile) for project in detection.projects
    ] == [
        ("pipelines/poc", ["python"], "python-uv"),
        ("pipelines/poc/web", ["javascript", "typescript"], "node-npm"),
    ]


def test_a_root_project_is_reported_as_the_repo_itself(tmp_path: Path) -> None:
    """The ordinary case keeps its answer: the root is the project, named `.`."""
    repo = init_repo(tmp_path / "app")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n')

    detection = detect_repo(repo)

    assert detection.languages == ["python"]
    assert [(project.path, project.languages) for project in detection.projects] == [
        (".", ["python"])
    ]


def test_a_nested_javascript_project_alone_gets_the_node_profile(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "site")
    app = repo / "apps" / "web"
    app.mkdir(parents=True)
    (app / "package.json").write_text("{}")

    detection = detect_repo(repo)

    assert detection.languages == ["javascript"]
    assert detection.profile == "node-npm"


def test_vendored_and_virtualenv_directories_are_not_scanned(tmp_path: Path) -> None:
    """node_modules and .venv hold thousands of tooling files that say nothing
    about what this repo is written in."""
    repo = init_repo(tmp_path / "app")
    for buried in (repo / "node_modules" / "left-pad", repo / ".venv" / "lib"):
        buried.mkdir(parents=True)
        (buried / "package.json").write_text("{}")
        (buried / "pyproject.toml").write_text('[project]\nname = "x"\n')

    detection = detect_repo(repo)

    assert detection.languages == []
    assert detection.projects == []


def test_the_scan_stops_at_its_depth_limit(tmp_path: Path) -> None:
    """A bound, so a large checkout is not walked end to end. Three levels
    reaches a service's web app; a project below that is the owner's to name in
    abk.yaml."""
    repo = init_repo(tmp_path / "deep")
    reachable = repo / "one" / "two" / "three"
    reachable.mkdir(parents=True)
    (reachable / "pyproject.toml").write_text('[project]\nname = "three"\n')
    too_deep = repo / "a" / "b" / "c" / "d"
    too_deep.mkdir(parents=True)
    (too_deep / "package.json").write_text("{}")

    detection = detect_repo(repo)

    assert detection.languages == ["python"]
    assert [project.path for project in detection.projects] == ["one/two/three"]


def test_a_requirements_file_inside_a_project_is_not_a_project_of_its_own(tmp_path: Path) -> None:
    """A deployment manifest is not a project. An Azure Functions directory
    carries `requirements.txt` beside the code it deploys, inside a project that
    already declares itself with a pyproject.toml; listing it as a project of
    its own says the repo has a build it does not have."""
    repo = init_repo(tmp_path / "accelerators")
    poc = repo / "poc"
    poc.mkdir()
    (poc / "pyproject.toml").write_text('[project]\nname = "poc"\n')
    functions = poc / "functions"
    functions.mkdir()
    (functions / "requirements.txt").write_text("azure-functions\n")

    detection = detect_repo(repo)

    assert [project.path for project in detection.projects] == ["poc"]


def test_a_repo_declared_only_by_a_requirements_file_is_still_a_project(tmp_path: Path) -> None:
    """The other side: plenty of Python repos declare themselves with nothing
    else, and nothing above them claims them."""
    repo = init_repo(tmp_path / "scripts")
    (repo / "requirements.txt").write_text("requests\n")

    detection = detect_repo(repo)

    assert [project.path for project in detection.projects] == ["."]
    assert detection.languages == ["python"]


def test_a_directory_it_may_not_read_does_not_stop_detection(tmp_path: Path) -> None:
    """A checkout carries runtime data as well as source — a data directory a
    service wrote as another user, say. Scanning for projects must step over
    what it cannot read rather than ending the run with a PermissionError."""
    if os.geteuid() == 0:
        pytest.skip("running as root: every directory is readable")
    repo = init_repo(tmp_path / "app")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n')
    blocked = repo / "service-data"
    (blocked / "inner").mkdir(parents=True)
    blocked.chmod(0o000)
    try:
        detection = detect_repo(repo)
    finally:
        blocked.chmod(0o755)

    assert [project.path for project in detection.projects] == ["."]


# --- which host the repo is on ----------------------------------------------------


def test_an_azure_devops_origin_is_recognised_and_decoded(tmp_path: Path) -> None:
    """The repo this was written for: `abk init` used to write
    `todo-owner/<name>` for it, because the only pattern it knew was GitHub's.
    Decoded, because `%20` handed to `az repos --project` names a project that
    does not exist."""
    repo = init_repo(tmp_path / "accelerators")
    git(repo, "remote", "add", "origin", "git@ssh.dev.azure.com:v3/acme/Some%20Project/Some%20Repo")

    detection = detect_repo(repo)

    assert detection.identity is not None
    assert detection.identity.forge == "azure_devops"
    assert detection.identity.account == "acme"
    assert detection.identity.project == "Some Project"
    assert detection.identity.name == "Some Repo"


def test_a_github_origin_still_yields_its_slug(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")

    detection = detect_repo(repo)

    assert detection.slug == "example/app"
    assert detection.identity is not None
    assert detection.identity.forge == "github"


def test_a_remote_no_forge_recognises_leaves_the_repo_unidentified(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "/srv/git/app.git")

    detection = detect_repo(repo)

    assert detection.identity is None
    assert detection.slug is None


# --- which branch work actually lands on -------------------------------------------


def test_the_branch_most_pull_requests_target_wins_over_origin_head(tmp_path: Path) -> None:
    """`origin/HEAD` is a pointer somebody set once and nobody updated. A repo
    that integrates on `dev` while HEAD still says `main` builds every unit on a
    branch the work is not on — the files the change names are simply absent."""
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    detection = detect_repo(repo, pr_bases=lambda identity: ["dev"] * 44 + ["main"] * 7)

    assert detection.default_branch == "dev"


def test_origin_head_stands_when_the_host_has_nothing_to_say(tmp_path: Path) -> None:
    """A new repo with no pull requests yet, or a host that cannot be reached."""
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")

    assert detect_repo(repo, pr_bases=lambda identity: []).default_branch == "develop"


def test_a_host_that_will_not_answer_does_not_fail_detection(tmp_path: Path) -> None:
    """Init runs before credentials are necessarily in place; a repo that cannot
    be asked is still detected."""
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")

    def refuses(identity):
        raise RuntimeError("not authenticated")

    assert detect_repo(repo, pr_bases=refuses).default_branch == "main"


def test_feature_branches_do_not_win_a_popularity_contest(tmp_path: Path) -> None:
    """Stacked work targets its parent branch, which is a target but never the
    repo's default. Only a branch that exists on the remote is considered."""
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")

    detection = detect_repo(
        repo, pr_bases=lambda identity: ["feature/x"] * 9 + ["dev"] * 2, remote_branches=["dev"]
    )

    assert detection.default_branch == "dev"
