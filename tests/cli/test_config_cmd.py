"""`abk config`: the effective config and its path."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit.cli import main
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump


def write_config(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    config = WorkspaceConfig(repos={"app": RepoConfig(path=root / "app", slug="example/app")})
    path = root / "abk.yaml"
    path.write_text(dump(config))
    return path


def test_show_fills_in_the_defaults(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path)

    code = main(["--config", str(path), "config", "--show"])

    assert code == 0
    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["repos"]["app"]["slug"] == "example/app"
    assert shown["repos"]["app"]["profile"] == "python-uv"
    assert shown["limits"]["max_concurrent_stacks"] == 4
    assert shown["github"]["branch_prefix"] == "spec/"


def test_show_is_the_default(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path)

    main(["--config", str(path), "config"])

    assert "branch_prefix" in capsys.readouterr().out


def test_path_prints_the_located_file(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path)

    code = main(["--config", str(path), "config", "--path"])

    assert code == 0
    assert capsys.readouterr().out.strip() == str(path.resolve())
