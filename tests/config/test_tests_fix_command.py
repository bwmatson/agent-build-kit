"""`repos.<name>.tests.fix_command`, the repo's own command for the fixer pass
(spec: fixers-run-before-commits)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import WorkspaceConfig, dump


def config(fix_command: Any = ...) -> WorkspaceConfig:
    app: dict[str, Any] = {"path": "/work/app", "slug": "example/app"}
    if fix_command is not ...:
        app["tests"] = {"fix_command": fix_command}
    return WorkspaceConfig.model_validate({"repos": {"app": app}})


def read(loaded: WorkspaceConfig) -> Any:
    return loaded.repos["app"].tests.model_dump()["fix_command"]


def test_a_list_of_strings_is_read_as_given() -> None:
    assert read(config(["scripts/format.sh", "--write"])) == ["scripts/format.sh", "--write"]


def test_unset_is_none() -> None:
    assert read(config()) is None


def test_the_empty_list_is_kept_apart_from_unset() -> None:
    assert read(config([])) == []


def test_a_non_string_entry_is_refused_naming_the_key() -> None:
    with pytest.raises(ValidationError) as refused:
        config(["scripts/format.sh", 3])

    [error] = refused.value.errors()
    assert error["type"] == "string_type"
    assert error["loc"][-2:] == ("fix_command", 1)


def test_config_show_prints_it(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config(["scripts/format.sh"])))

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["repos"]["app"]["tests"]["fix_command"] == ["scripts/format.sh"]
