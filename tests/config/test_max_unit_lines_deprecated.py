"""`global_limits.max_unit_lines` is deprecated, read as the `full` ceiling."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.config import ConfigError, deprecations, load, overlay_path, review_ceiling
from agent_build_kit.pipeline.verdict import ReviewTier

DEPRECATED = "global_limits.max_unit_lines"
REPOS = {"app": {"path": "/work/app", "slug": "example/app"}}


def write(root: Path, document: dict[str, Any], overlay: dict[str, Any] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "abk.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "repos": REPOS, **document}))
    if overlay is not None:
        overlay_path(path).write_text(yaml.safe_dump(overlay))
    return path


def full_ceiling(path: Path) -> int:
    config = load(path)
    return review_ceiling(config.repos["app"], config, ReviewTier.FULL)


def test_the_deprecated_key_alone_is_the_full_ceiling_and_is_noticed(tmp_path: Path) -> None:
    path = write(tmp_path, {"global_limits": {"max_unit_lines": 600}})

    assert full_ceiling(path) == 600
    assert deprecations(path) == [DEPRECATED]


def test_the_full_ceiling_alone_is_the_ceiling_with_no_notice(tmp_path: Path) -> None:
    new = write(tmp_path / "new", {"review": {"ceilings": {"full": 600}}})
    old = write(tmp_path / "old", {"global_limits": {"max_unit_lines": 600}})

    assert full_ceiling(new) == 600
    assert deprecations(new) == []
    assert deprecations(old) == [DEPRECATED]


def test_the_two_keys_set_to_different_values_fail_naming_both(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {"global_limits": {"max_unit_lines": 600}, "review": {"ceilings": {"full": 700}}},
    )

    with pytest.raises(ConfigError) as refused:
        load(path)

    message = str(refused.value)
    assert all(word in message for word in (DEPRECATED, "review.ceilings.full", "600", "700"))


def test_the_two_keys_set_to_the_same_value_load_and_the_key_is_still_noticed(
    tmp_path: Path,
) -> None:
    path = write(
        tmp_path,
        {"global_limits": {"max_unit_lines": 750}, "review": {"ceilings": {"full": 750}}},
    )

    assert full_ceiling(path) == 750
    assert deprecations(path) == [DEPRECATED]


def test_the_floor_is_checked_against_the_full_ceiling_whichever_key_sets_it(
    tmp_path: Path,
) -> None:
    old = write(tmp_path / "old", {"global_limits": {"max_unit_lines": 300, "min_unit_lines": 400}})
    new = write(
        tmp_path / "new",
        {"global_limits": {"min_unit_lines": 400}, "review": {"ceilings": {"full": 300}}},
    )

    for path in (old, new):
        with pytest.raises(ConfigError) as refused:
            load(path)
        assert all(word in str(refused.value) for word in ("min_unit_lines", "300", "400"))
    assert deprecations(old) == [DEPRECATED]


def test_the_key_set_in_the_overlay_is_read_the_same_way(tmp_path: Path) -> None:
    alone = write(tmp_path / "alone", {}, overlay={"global_limits": {"max_unit_lines": 600}})
    clash = write(
        tmp_path / "clash",
        {"review": {"ceilings": {"full": 700}}},
        overlay={"global_limits": {"max_unit_lines": 600}},
    )

    assert full_ceiling(alone) == 600
    assert deprecations(alone) == [DEPRECATED]
    with pytest.raises(ConfigError) as refused:
        load(clash)
    assert all(word in str(refused.value) for word in (DEPRECATED, "600", "700"))
