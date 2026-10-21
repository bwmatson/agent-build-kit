"""`abk config` shows `e2e_before_merge` as set, and the `abk init` template carries it commented
out with its default (spec: e2e-before-merge)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.config import WorkspaceConfig, dump
from agent_build_kit.init.scaffold import dump_with_notes


def workspace(tmp_path: Path, limits: dict[str, Any], **tests: Any) -> WorkspaceConfig:
    return WorkspaceConfig.model_validate(
        {
            "global_limits": limits,
            "repos": {
                "app": {"path": str(tmp_path / "app"), "slug": "example/app", "tests": tests},
                "platform": {"path": str(tmp_path / "platform"), "slug": "example/platform"},
            },
        }
    )


def shown(tmp_path: Path, config: WorkspaceConfig, capsys: pytest.CaptureFixture) -> Any:
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config))
    assert main(["--config", str(path), "config", "--show"]) == 0
    return yaml.safe_load(capsys.readouterr().out)


def test_the_global_value_is_printed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    out = shown(tmp_path, workspace(tmp_path, {"e2e_before_merge": "deferred"}), capsys)

    assert out["global_limits"]["e2e_before_merge"] == "deferred"


def test_a_repo_that_sets_its_own_value_shows_it(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    out = shown(tmp_path, workspace(tmp_path, {}, e2e_before_merge="deferred"), capsys)

    assert out["global_limits"]["e2e_before_merge"] == "required"
    assert out["repos"]["app"]["tests"]["e2e_before_merge"] == "deferred"


def test_no_repo_value_is_printed_when_none_sets_one(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    out = shown(tmp_path, workspace(tmp_path, {}), capsys)

    assert out["global_limits"]["e2e_before_merge"] == "required"
    assert not out["repos"]["app"]["tests"].get("e2e_before_merge")
    assert not out["repos"]["platform"].get("tests", {}).get("e2e_before_merge")


def test_the_init_template_has_the_setting_commented_out_with_its_default(
    tmp_path: Path,
) -> None:
    text = dump_with_notes(workspace(tmp_path, {}))

    assert re.search(r"^\s*#\s*e2e_before_merge:\s*required\b", text, re.MULTILINE)
    assert not re.search(r"^\s*e2e_before_merge:", text, re.MULTILINE)


def test_the_commented_setting_goes_inside_an_existing_global_limits_section(
    tmp_path: Path,
) -> None:
    text = dump_with_notes(workspace(tmp_path, {"generated_files": ["*.lock"]}))

    assert len(re.findall(r"^#?\s*global_limits:", text, re.MULTILINE)) == 1
    uncommented = re.sub(r"^(\s*)# (e2e_before_merge:)", r"\1\2", text, flags=re.MULTILINE)
    limits = yaml.safe_load(uncommented)["global_limits"]
    assert limits["generated_files"] == ["*.lock"]
    assert limits["e2e_before_merge"] == "required"
