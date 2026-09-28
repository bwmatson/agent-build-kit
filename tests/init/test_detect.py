"""What `abk init` reads off a checkout.

Real temporary git repos rather than a fake runner: the questions are about
git's answers (the origin URL, the remote HEAD, tracked files), and a fake
would only restate the test's own assumptions about them.
"""

from __future__ import annotations

import json
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
