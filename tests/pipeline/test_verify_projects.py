"""Post-merge verify classifies paths and finds members through the profile of the project
each belongs to, not the repo's (spec: node-npm-workspaces)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.config import DeployConfig, DeployRule, ProjectConfig, RepoConfig
from agent_build_kit.pipeline.verify import deploy_commands, verify_change
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.node_workspace import manifest, touch, workspace


def mixed_repo(root: Path) -> RepoConfig:
    """A python repo with a node project under `web/`."""
    return RepoConfig(
        path=root,
        slug="example/platform",
        projects=[ProjectConfig(path="."), ProjectConfig(path="web", profile="node-npm")],
        deploy=DeployConfig(
            rules=[
                DeployRule(prefix="web/packages/app/", run=[["deploy", "app"]]),
                DeployRule(prefix="web/packages/lib/", run=[["deploy", "lib"]]),
                DeployRule(prefix="web/", run=[["deploy", "web"]]),
            ]
        ),
    )


def test_a_node_test_file_in_a_mixed_repo_deploys_nothing(tmp_path: Path) -> None:
    manifest(tmp_path / "web", "web")

    commands = deploy_commands(
        mixed_repo(tmp_path),
        ["web/src/index.test.ts", "web/src/__tests__/helper.ts"],
        checkout=tmp_path,
    )

    assert commands == []


def test_a_node_librarys_dependents_are_deployed_with_it(tmp_path: Path) -> None:
    web = tmp_path / "web"
    workspace(web, ["packages/lib", "packages/app", "packages/other"])
    manifest(web / "packages" / "lib", "lib")
    manifest(web / "packages" / "app", "app", dependencies={"lib": "*"})

    commands = deploy_commands(
        mixed_repo(tmp_path), ["web/packages/lib/src/x.ts"], checkout=tmp_path
    )

    assert commands == [("deploy", "lib"), ("deploy", "app")]


def test_each_projects_live_tests_run_from_its_directory_with_its_own_paths(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkouts" / "platform"
    installation = make_installation(
        tmp_path,
        repos={
            "platform": {
                "path": str(checkout),
                "slug": "example/platform",
                "projects": [{"path": "."}, {"path": "web", "profile": "node-npm"}],
            }
        },
    )
    manifest(checkout / "web", "web")
    touch(checkout, "web/src/live.local_stack.test.ts", "tests/integration/test_live.py")
    ran: list[tuple[Path, list[str]]] = []

    def run(command, *, cwd, env=None, **kwargs):
        ran.append((Path(cwd), list(command)))
        out = "main" if command[:2] == ["git", "rev-parse"] else ""
        return subprocess.CompletedProcess(command, 0, out, "")

    result = verify_change(
        "c",
        [stored_unit("c/1", change="c", repo="platform", state="merged", pr=1)],
        installation=installation,
        pr_files=lambda repo, pr: [
            "web/src/live.local_stack.test.ts",
            "tests/integration/test_live.py",
        ],
        run=run,
    )

    assert result.passed, result.detail
    live = [(cwd, command) for cwd, command in ran if command[0] not in ("git",)]
    (node,) = [(cwd, c) for cwd, c in live if "sh" == c[0]]
    (python,) = [(cwd, c) for cwd, c in live if "pytest" in c]
    assert node[0] == checkout / "web"
    assert "src/live.local_stack.test.ts" in node[1]
    assert "web/src/live.local_stack.test.ts" not in node[1]
    assert python[0] == checkout
    assert python[1][-1] == "tests/integration/test_live.py"
    assert not any("web/" in word for word in python[1])
