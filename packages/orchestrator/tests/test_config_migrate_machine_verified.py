"""The in-memory check before anything is written, a second run, and the defaults flag."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from agent_build_kit import config_migrate_machine
from agent_build_kit.config_migrate import ConfigMigrateError
from agent_build_kit.config_migrate_machine import check_move, move_machine_settings
from agent_build_kit.machine_settings import machine_settings
from tests.config_migrate_machine_support import merged, request

OLD = "repos:\n  app:\n    slug: example/app\n    path: ../app\n"
MOVED = (("repos", "app", "path"),)
GOOD_BASE = "repos:\n  app:\n    slug: example/app\n"
GOOD_LOCAL = "repos:\n  app:\n    path: ../app\n"

# name -> (the new tracked text, the new local text, the key named)
BAD = {
    "a placement that drops a key": (GOOD_BASE, "repos:\n  app: {}\n", "repos.app.path"),
    "a placement that changes a value": (
        GOOD_BASE,
        "repos:\n  app:\n    path: ../other\n",
        "repos.app.path",
    ),
    "a placement that adds a key": (
        GOOD_BASE,
        GOOD_LOCAL + "    extra: 1\n",
        "repos.app.extra",
    ),
    "a tracked text that loses another key": (
        "repos:\n  app: {}\n",
        GOOD_LOCAL,
        "repos.app.slug",
    ),
}


def test_a_move_that_keeps_the_merged_configuration_passes() -> None:
    check_move(OLD, None, GOOD_BASE, GOOD_LOCAL, MOVED)


@pytest.mark.parametrize("name", BAD)
def test_a_move_that_changes_the_merged_configuration_is_refused_naming_the_key(
    name: str,
) -> None:
    new_base, new_local, key = BAD[name]

    with pytest.raises(ConfigMigrateError) as refused:
        check_move(OLD, None, new_base, new_local, MOVED)

    assert key in str(refused.value), str(refused.value)


def test_a_move_run_again_over_its_own_output_changes_nothing(tmp_path: Path) -> None:
    base = OLD + "planning:\n  worktree_root: /opt/trees\n"
    local = "planning:\n  worktree_root: /opt/mine\n"
    first = move_machine_settings(base, request(tmp_path, local))
    assert first.local_text is not None

    second = move_machine_settings(first.text, request(tmp_path, first.local_text))

    assert second.moved == ()
    assert second.text == first.text
    assert second.local_text == first.local_text
    assert second.conflicts == first.conflicts
    assert len(second.conflicts) == 1


DEFAULTS = (
    "repos:\n  app:\n    slug: example/app\n    account: personal\n"
    "runtimes:\n  claude:\n    limits:\n      five_hour: 50\n"
    "tests:\n  e2e_schedule: off\n  e2e_splits:\n    fast:\n      hold: true\n"
)


def test_the_defaults_of_the_table_move_only_with_the_flag(tmp_path: Path) -> None:
    listed = machine_settings(yaml.safe_load(DEFAULTS), tmp_path / "planning")
    machine = {s.path for s in listed if s.kind == "machine"}
    defaults = {s.path for s in listed if s.kind == "default"}
    assert machine and defaults

    without = move_machine_settings(DEFAULTS, request(tmp_path))
    with_defaults = move_machine_settings(DEFAULTS, request(tmp_path, defaults=True))

    assert set(without.moved) == machine
    assert set(with_defaults.moved) == machine | defaults
    assert "e2e_schedule" in without.text
    assert "e2e_schedule" not in with_defaults.text
    assert merged(with_defaults.text, with_defaults.local_text) == merged(DEFAULTS, None)


def test_without_the_flag_a_text_of_only_defaults_is_untouched(tmp_path: Path) -> None:
    base = "tests:\n  e2e_schedule: off\n"

    result = move_machine_settings(base, request(tmp_path))

    assert result.moved == ()
    assert result.text == base
    assert result.local_text is None


def _drop(lines: list[str]) -> list[str]:
    return []


def _change(lines: list[str]) -> list[str]:
    return [line.replace("../app", "../other") for line in lines]


def _add(lines: list[str]) -> list[str]:
    indent = " " * (len(lines[0]) - len(lines[0].lstrip()))
    return [*lines, f"{indent}extra: 1"]


@pytest.mark.parametrize("broken", [_drop, _change, _add], ids=["drops", "changes", "adds"])
def test_a_broken_placement_is_refused_before_a_result_is_returned(
    broken: Callable[[list[str]], list[str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = config_migrate_machine.shifted
    monkeypatch.setattr(
        config_migrate_machine, "shifted", lambda lines, by: broken(real(lines, by))
    )

    with pytest.raises(ConfigMigrateError) as refused:
        move_machine_settings(OLD, request(tmp_path))

    assert "repos.app" in str(refused.value), str(refused.value)
