"""`repos.<name>.agent_commands`: replacing a profile's commands, and refusing one the build
allow-list would refuse (spec: toolchain-profiles)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit import profiles
from agent_build_kit.cli import main
from agent_build_kit.config import (
    ConfigError,
    ProjectConfig,
    RepoConfig,
    WorkspaceConfig,
    dump,
    load,
)
from agent_build_kit.pipeline.agent_commands import effective
from tests.agent_command_fakes import command

GOOD = "uv run pytest -q"


def lines(repo: RepoConfig) -> list[str]:
    return [" ".join(c.command) for c in effective(repo)]


def profile_lines(*names: str) -> list[str]:
    return [" ".join(c.command) for name in names for c in profiles.get(name).agent_commands]  # type: ignore[attr-defined]


def repo_of(tmp_path: Path, **fields: object) -> RepoConfig:
    return RepoConfig(path=tmp_path, slug="example/app", **fields)  # type: ignore[arg-type]


def write(tmp_path: Path, entries: list[str], *, projects: str = "") -> Path:
    items = "".join(f"      - purpose: test\n        command: {entry!r}\n" for entry in entries)
    path = tmp_path / "abk.yaml"
    path.write_text(
        "repos:\n"
        "  app:\n"
        f"    path: {tmp_path}\n"
        "    slug: example/app\n"
        f"{projects}"
        f"    agent_commands:\n{items}"
    )
    return path


def test_by_default_the_repo_follows_its_profile_and_config_show_says_null(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = repo_of(tmp_path)
    path = tmp_path / "abk.yaml"
    path.write_text(dump(WorkspaceConfig(repos={"app": repo})))

    code = main(["--config", str(path), "config", "--show"])

    out = capsys.readouterr().out
    assert code == 0
    assert repo.agent_commands is None
    assert "agent_commands: null" in out
    assert yaml.safe_load(out)["repos"]["app"]["agent_commands"] is None
    assert lines(repo) == profile_lines("python-uv")


def test_a_list_replaces_the_profiles_commands_in_order(tmp_path: Path) -> None:
    repo = repo_of(
        tmp_path,
        agent_commands=[command("lint", "uv run ruff check ."), command("test", GOOD)],
    )

    assert lines(repo) == ["uv run ruff check .", GOOD]


def test_an_empty_list_means_none(tmp_path: Path) -> None:
    assert lines(repo_of(tmp_path, agent_commands=[])) == []


def test_a_repo_with_projects_has_the_repo_profiles_commands_then_each_projects_once(
    tmp_path: Path,
) -> None:
    repo = repo_of(
        tmp_path,
        projects=[
            ProjectConfig(path=".", profile="python-uv"),
            ProjectConfig(path="web", profile="node-npm"),
            ProjectConfig(path="web2", profile="node-npm"),
        ],
    )

    assert lines(repo) == profile_lines("python-uv", "node-npm")


@pytest.mark.parametrize(
    "refused",
    ["python -m pytest tests -q", "ruff check .", "uv run pytest -q; echo $?"],
)
def test_a_command_the_allow_list_refuses_stops_the_load_naming_where(
    tmp_path: Path, refused: str
) -> None:
    assert load(write(tmp_path, [GOOD, GOOD])).repos["app"].agent_commands is not None

    with pytest.raises(ConfigError) as error:
        load(write(tmp_path, [GOOD, refused]))

    message = str(error.value)
    assert "app" in message
    assert "agent_commands[1]" in message
    assert refused in message
    assert "Bash(uv run *)" in message, "the allow-list"


def test_the_allow_list_is_the_one_the_build_starts_with_including_project_profiles(
    tmp_path: Path,
) -> None:
    web = "    projects:\n      - path: .\n        profile: python-uv\n"
    web += "      - path: web\n        profile: node-npm\n"
    assert load(write(tmp_path, ["npx vitest run"], projects=web))

    with pytest.raises(ConfigError, match="npx vitest run"):
        load(write(tmp_path, ["npx vitest run"]))
