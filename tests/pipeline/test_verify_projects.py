"""Post-merge verify classifies paths and finds members through the profile of the project
each belongs to, not the repo's (spec: node-npm-workspaces)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import DeployConfig, DeployRule, ProjectConfig, RepoConfig
from agent_build_kit.pipeline.verify import deploy_commands
from tests.node_workspace import manifest, workspace


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
