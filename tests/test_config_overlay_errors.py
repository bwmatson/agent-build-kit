"""A broken overlay, and a schema error, name the file the failing key came from."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.config import ConfigError, load

APP = {"path": ".", "slug": "example/app"}


def committed(root: Path, document: dict | None = None) -> Path:
    path = root / "abk.yaml"
    path.write_text(yaml.safe_dump(document or {"repos": {"app": APP}}))
    return path


def test_a_top_level_list_in_the_overlay_is_a_configuration_error(tmp_path: Path) -> None:
    path = committed(tmp_path)
    (tmp_path / "abk.local.yaml").write_text("- one\n- two\n")

    with pytest.raises(ConfigError, match="abk.local.yaml") as raised:
        load(path)

    assert "mapping" in str(raised.value)


def test_invalid_yaml_in_the_overlay_names_it(tmp_path: Path) -> None:
    path = committed(tmp_path)
    (tmp_path / "abk.local.yaml").write_text("repos: [unclosed\n")

    with pytest.raises(ConfigError, match="abk.local.yaml"):
        load(path)


def test_an_unreadable_overlay_names_it(tmp_path: Path) -> None:
    path = committed(tmp_path)
    (tmp_path / "abk.local.yaml").mkdir()

    with pytest.raises(ConfigError, match="abk.local.yaml"):
        load(path)


def test_a_misspelled_key_names_the_file_it_is_in_and_its_path(tmp_path: Path) -> None:
    path = committed(tmp_path)
    (tmp_path / "abk.local.yaml").write_text(yaml.safe_dump({"repos": {"app": {"slgu": "x/y"}}}))

    with pytest.raises(ConfigError) as in_overlay:
        load(path)

    shown = str(in_overlay.value)
    assert "abk.local.yaml" in shown
    assert "repos.app.slgu" in shown

    (tmp_path / "abk.local.yaml").unlink()
    path = committed(tmp_path, {"repos": {"app": {**APP, "slgu": "x/y"}}})
    (tmp_path / "abk.local.yaml").write_text(yaml.safe_dump({"git": {"branch_prefix": "x/"}}))

    with pytest.raises(ConfigError) as in_committed:
        load(path)

    shown = str(in_committed.value)
    assert "abk.yaml" in shown
    assert "abk.local.yaml" not in shown
    assert "repos.app.slgu" in shown


def test_a_value_only_the_combination_makes_invalid_names_both_files(tmp_path: Path) -> None:
    path = committed(tmp_path, {"repos": {"app": APP}, "global_limits": {"min_unit_lines": 700}})
    (tmp_path / "abk.local.yaml").write_text(
        yaml.safe_dump({"global_limits": {"max_unit_lines": 600}})
    )

    with pytest.raises(ConfigError) as raised:
        load(path)

    shown = str(raised.value)
    assert "abk.local.yaml" in shown
    assert str(path) in shown
