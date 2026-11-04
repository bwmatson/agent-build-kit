"""`global_limits.code_host_outage_minutes`: how long a code host's probes fail in a row before the
status, the tick log and `abk doctor` say so (the units stay parked)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import LimitsConfig, RepoConfig, WorkspaceConfig, dump


def limits(**values: Any) -> Any:
    return LimitsConfig.model_validate(values)


def test_the_limit_is_sixty_minutes_by_default() -> None:
    assert limits().code_host_outage_minutes == 60


def test_a_whole_number_of_minutes_is_taken() -> None:
    assert limits(code_host_outage_minutes=15).code_host_outage_minutes == 15


@pytest.mark.parametrize("value", [0, -1, 2.5])
def test_anything_else_is_refused_by_name(value: float) -> None:
    with pytest.raises(ValidationError, match="code_host_outage_minutes") as refused:
        limits(code_host_outage_minutes=value)

    assert "Extra inputs" not in str(refused.value)


def test_config_show_lists_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = WorkspaceConfig(repos={"app": RepoConfig(path=tmp_path / "app", slug="example/app")})
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config))

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)["global_limits"]
    assert shown["code_host_outage_minutes"] == 60
