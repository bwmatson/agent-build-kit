"""A python-uv build step sets the unit's selection data file and the coverage core in its
agent's environment, so the affected-tests command matches the allow-list (spec:
agent-test-commands); a repo with another profile, or with declared projects, gets neither."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.pipeline.wiring import agent_environment, build_run
from tests.agent_command_fakes import NoEnvironment
from tests.pipeline.test_scratch_folder import MODEL, repo, tree  # noqa: F401
from tests.runtimes.stand_in import StandInRuntime


def test_a_python_uv_repo_gets_the_data_file_and_the_coverage_core(tmp_path: Path) -> None:
    config = RepoConfig(path=tmp_path, slug="example/app", profile="python-uv")

    env = agent_environment(config, tmp_path)

    assert env == {
        "TESTMON_DATAFILE": str(tmp_path / ".abk" / "affected"),
        "COVERAGE_CORE": "ctrace",
    }


def test_asking_makes_no_folder(tmp_path: Path) -> None:
    config = RepoConfig(path=tmp_path, slug="example/app", profile="python-uv")

    agent_environment(config, tmp_path)

    assert not (tmp_path / ".abk").exists()


def test_a_node_npm_repo_gets_neither(tmp_path: Path) -> None:
    config = RepoConfig(path=tmp_path, slug="example/app", profile="node-npm")

    assert agent_environment(config, tmp_path) == {}


def test_a_profile_without_the_environment_gets_neither(tmp_path: Path) -> None:
    with profiles.registered(NoEnvironment()):
        config = RepoConfig(path=tmp_path, slug="example/app", profile="fake-no-environment")

        assert agent_environment(config, tmp_path) == {}


def test_a_repo_with_projects_gets_neither(tmp_path: Path) -> None:
    config = RepoConfig(
        path=tmp_path,
        slug="example/app",
        profile="python-uv",
        projects=[ProjectConfig(path="service", profile="python-uv")],
    )

    assert agent_environment(config, tmp_path) == {}


def test_no_repo_gets_nothing(tmp_path: Path) -> None:
    assert agent_environment(None, tmp_path) == {}


def test_a_build_run_of_a_python_uv_repo_carries_it_to_the_agent(tree: Path) -> None:  # noqa: F811
    seen: list[dict[str, str]] = []
    runtime = StandInRuntime(act=lambda request: seen.append(dict(request.env)))

    build_run(runtime=runtime, sandbox_repo="app")("Implement it.", cwd=tree, model=MODEL)

    [env] = seen
    assert env["TESTMON_DATAFILE"] == str(tree / ".abk" / "affected")
    assert env["COVERAGE_CORE"] == "ctrace"
