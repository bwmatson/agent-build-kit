"""`planning.publish` says whether abk's planning commits go to the default branch or a branch."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit import config
from agent_build_kit.cli import main
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from agent_build_kit.pipeline.planning_sync import PlanningMode, planning_mode
from tests.conftest import make_installation


def load_text(tmp_path: Path, text: str) -> config.WorkspaceConfig:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    return config.load(path)


def test_the_default_is_direct(tmp_path: Path) -> None:
    assert load_text(tmp_path, "version: 1\n").planning.model_dump()["publish"] == "direct"


def test_branch_is_accepted(tmp_path: Path) -> None:
    loaded = load_text(tmp_path, "version: 1\nplanning:\n  publish: branch\n")

    assert loaded.planning.model_dump()["publish"] == "branch"


@pytest.mark.parametrize("value", ["pr", "Direct", "other"])
def test_any_other_value_is_refused_naming_the_setting_and_both_values(
    tmp_path: Path, value: str
) -> None:
    with pytest.raises(config.ConfigError) as refused:
        load_text(tmp_path, f"version: 1\nplanning:\n  publish: {value}\n")

    message = str(refused.value)
    assert "planning.publish" in message
    assert "direct" in message
    assert "branch" in message
    assert "Extra inputs" not in message


@pytest.mark.parametrize("value", ["direct", "branch"])
def test_config_show_prints_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    workspace = WorkspaceConfig(
        repos={"app": RepoConfig(path=tmp_path / "app", slug="example/app")}
    )
    path = tmp_path / "abk.yaml"
    written = yaml.safe_load(dump(workspace))
    written.setdefault("planning", {})["publish"] = value
    path.write_text(yaml.safe_dump(written))

    assert main(["--config", str(path), "config", "--show"]) == 0

    assert yaml.safe_load(capsys.readouterr().out)["planning"]["publish"] == value


def test_it_has_no_effect_on_a_separate_root(tmp_path: Path) -> None:
    plain = make_installation(tmp_path / "plain")
    branch = make_installation(tmp_path / "branch", planning=dict(publish="branch"))

    assert planning_mode(plain) == PlanningMode.SEPARATE
    assert planning_mode(branch) == PlanningMode.SEPARATE
