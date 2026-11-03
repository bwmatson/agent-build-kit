"""A python-uv build step sets the unit's selection data file and the coverage core in its
agent's environment, so the affected-tests command matches the allow-list (spec:
agent-test-commands); a repo with another profile, or with declared projects, gets neither."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.pipeline.wiring import agent_environment, build_run
from tests.agent_command_fakes import Bare
from tests.factories import git
from tests.pipeline.test_scratch_folder import MODEL, repo, tree  # noqa: F401
from tests.runtimes.stand_in import StandInRuntime


def test_a_python_uv_repo_gets_the_data_file_and_the_coverage_core(tmp_path: Path) -> None:
    config = RepoConfig(path=tmp_path, slug="example/app", profile="python-uv")

    env = agent_environment(config, tmp_path)

    assert env == {
        "TESTMON_DATAFILE": str(tmp_path / ".abk" / "affected-agent"),
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
    with profiles.registered(Bare()):  # type: ignore[arg-type]
        config = RepoConfig(path=tmp_path, slug="example/app", profile="fake-bare")

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
    assert env["TESTMON_DATAFILE"] == str(tree / ".abk" / "affected-agent")
    assert env["COVERAGE_CORE"] == "ctrace"


def python_uv_repo(path: Path) -> RepoConfig:
    return RepoConfig(path=path, slug="example/app", profile="python-uv")


def test_the_pipelines_data_is_copied_for_the_agent_and_the_original_is_left_alone(
    tmp_path: Path,
) -> None:
    (tmp_path / ".abk").mkdir()
    (tmp_path / ".abk" / "affected").write_text("recorded by the first full run")

    env = agent_environment(python_uv_repo(tmp_path), tmp_path)
    Path(env["TESTMON_DATAFILE"]).write_text("rewritten by the agent's run")

    assert (tmp_path / ".abk" / "affected").read_text() == "recorded by the first full run"


def test_an_agent_run_before_the_pipeline_has_data_leaves_nothing_the_pipeline_trusts(
    tmp_path: Path,
) -> None:
    (tmp_path / ".abk").mkdir()

    env = agent_environment(python_uv_repo(tmp_path), tmp_path)
    Path(env["TESTMON_DATAFILE"]).write_text("a partial agent run")

    assert not (tmp_path / ".abk" / "affected").exists()


def test_a_later_step_takes_the_pipelines_fresher_data(tmp_path: Path) -> None:
    (tmp_path / ".abk").mkdir()
    (tmp_path / ".abk" / "affected-agent").write_text("an earlier agent run")
    (tmp_path / ".abk" / "affected").write_text("the pipeline's newer data")

    env = agent_environment(python_uv_repo(tmp_path), tmp_path)

    assert Path(env["TESTMON_DATAFILE"]).read_text() == "the pipeline's newer data"


def test_a_worktree_excludes_the_data_file_testmon_writes_without_a_variable(
    tree: Path,  # noqa: F811
) -> None:
    path = Path(git(tree, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"))

    assert ".testmondata*" in path.read_text().splitlines()
