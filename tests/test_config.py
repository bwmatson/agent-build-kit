"""The workspace configuration: what `abk.yaml` may say, and what it may not.

The schema refuses at load rather than at the moment a value would have
mattered, so a configuration that cannot be satisfied never reaches a plan.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.config import ConfigError, LimitsConfig, load


def test_the_ceiling_on_a_unit_defaults_to_a_thousand_lines() -> None:
    """With nothing configured, the default floor still sits under it, and a
    floor raised to meet it is refused — the default is a ceiling, not a
    number nothing reads."""
    assert LimitsConfig().max_unit_lines == 1000

    with pytest.raises(ValidationError):
        LimitsConfig(min_unit_lines=1000)


def test_a_floor_above_the_ceiling_is_refused_naming_both() -> None:
    """No plan could satisfy both, so it fails here rather than producing
    units that miss one or the other."""
    with pytest.raises(ValidationError) as refused:
        LimitsConfig(min_unit_lines=1200, max_unit_lines=800)

    message = str(refused.value)
    assert "min_unit_lines" in message and "1200" in message
    assert "max_unit_lines" in message and "800" in message


def test_a_floor_equal_to_the_ceiling_is_refused() -> None:
    """The ceiling must exceed the floor: at equality every unit would have to
    land on exactly one number."""
    with pytest.raises(ValidationError) as refused:
        LimitsConfig(min_unit_lines=700, max_unit_lines=700)

    assert "min_unit_lines" in str(refused.value)


def test_abk_yaml_with_the_floor_above_the_ceiling_fails_to_load(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text("limits:\n  min_unit_lines: 1500\n  max_unit_lines: 900\n")

    with pytest.raises(ConfigError) as refused:
        load(path)

    message = str(refused.value)
    assert "1500" in message and "900" in message
    assert "min_unit_lines" in message
