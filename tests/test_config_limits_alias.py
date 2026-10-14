"""`limits` at the root loads as `global_limits`, and is listed as deprecated."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    return path


def test_the_old_key_alone_loads_as_the_new_one(tmp_path: Path) -> None:
    old = config.load(write(tmp_path, "version: 1\nlimits:\n  max_review_rounds: 5\n"))
    new = config.load(write(tmp_path, "version: 1\nglobal_limits:\n  max_review_rounds: 5\n"))

    old_block = old.global_limits  # pyrefly: ignore
    assert old_block == new.global_limits  # pyrefly: ignore
    assert old_block.max_review_rounds == 5


def test_both_keys_fail_naming_both_and_saying_to_keep_one(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "version: 1\nlimits:\n  max_review_rounds: 5\nglobal_limits:\n  max_review_rounds: 6\n",
    )

    with pytest.raises(config.ConfigError) as refused:
        config.load(path)

    message = str(refused.value)
    assert "`limits`" in message
    assert "`global_limits`" in message
    assert "keep one" in message


def test_an_invalid_value_under_the_alias_is_reported_as_the_file_spells_it(
    tmp_path: Path,
) -> None:
    path = write(tmp_path, "version: 1\nlimits:\n  max_review_rounds: many\n")

    with pytest.raises(config.ConfigError) as refused:
        config.load(path)

    message = str(refused.value)
    assert "limits.max_review_rounds" in message
    assert "global_limits.max_review_rounds" not in message

    with pytest.raises(config.ConfigError, match=r"global_limits\.max_review_rounds"):
        config.load(write(tmp_path, "version: 1\nglobal_limits:\n  max_review_rounds: many\n"))


def test_the_alias_is_listed_as_deprecated_for_a_file_that_uses_it(tmp_path: Path) -> None:
    path = write(tmp_path, "version: 1\nlimits:\n  max_review_rounds: 5\n")

    assert config.deprecations(path) == ["limits"]


def test_nothing_is_listed_for_a_file_that_does_not(tmp_path: Path) -> None:
    path = write(tmp_path, "version: 1\nglobal_limits:\n  max_review_rounds: 5\n")

    assert config.deprecations(path) == []
