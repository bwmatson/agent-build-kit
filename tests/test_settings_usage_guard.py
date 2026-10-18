"""`ABK_USAGE_GUARD` is a per-machine setting of `on` or `off`, and never a key of `abk.yaml`."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.config import ConfigError, load
from agent_build_kit.settings import Settings


def test_the_setting_accepts_on_and_off_and_defaults_to_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ABK_USAGE_GUARD", raising=False)
    assert Settings(_env_file=None).usage_guard == "on"

    for value in ("on", "off"):
        monkeypatch.setenv("ABK_USAGE_GUARD", value)
        assert Settings(_env_file=None).usage_guard == value


def test_another_value_is_refused_naming_the_setting_and_both_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ABK_USAGE_GUARD", "maybe")

    with pytest.raises(ValidationError) as refused:
        Settings(_env_file=None)

    message = str(refused.value)
    assert "usage_guard" in message.lower()
    assert "'on'" in message
    assert "'off'" in message


def test_usage_guard_is_a_setting_and_as_a_key_of_abk_yaml_it_is_an_unknown_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ABK_USAGE_GUARD", raising=False)
    assert Settings(_env_file=None).usage_guard == "on"
    path = tmp_path / "abk.yaml"
    path.write_text("usage_guard: off\n")

    with pytest.raises(ConfigError) as refused:
        load(path)

    assert "usage_guard" in str(refused.value)
