"""`limits.service_unavailable_attempts`.

How many times in a row a unit may be parked because the model service answered 5xx or 529
before the next such failure fails it: a persistent 5xx can be a real fault.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import LimitsConfig, RepoConfig, WorkspaceConfig, dump


def limits(**values: Any) -> Any:
    """The limits as the configuration file gives them, read through the schema."""
    return LimitsConfig.model_validate(values)


def test_the_attempts_are_five_by_default() -> None:
    assert limits().service_unavailable_attempts == 5


def test_a_positive_whole_number_is_taken() -> None:
    assert limits(service_unavailable_attempts=3).service_unavailable_attempts == 3


@pytest.mark.parametrize("value", [0, -1, 2.5])
def test_a_count_that_is_not_a_positive_whole_number_is_refused_by_name(value: float) -> None:
    assert limits(service_unavailable_attempts=1).service_unavailable_attempts == 1

    with pytest.raises(ValidationError, match="service_unavailable_attempts") as refused:
        limits(service_unavailable_attempts=value)

    assert "Extra inputs" not in str(refused.value)


def test_config_show_lists_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = WorkspaceConfig(repos={"app": RepoConfig(path=tmp_path / "app", slug="example/app")})
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config))

    assert main(["--config", str(path), "config", "--show"]) == 0

    assert (
        yaml.safe_load(capsys.readouterr().out)["global_limits"]["service_unavailable_attempts"]
        == 5
    )
