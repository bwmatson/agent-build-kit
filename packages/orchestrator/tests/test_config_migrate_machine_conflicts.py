"""A setting the local file already sets is left in abk.yaml and reported, never overwritten."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config_migrate_machine import Conflict, move_machine_settings
from tests.config_migrate_machine_support import merged, request

PATH = ("repos", "app", "path")
APP = "repos:\n  app:\n    slug: example/app\n    path: ../app\n"
LIMITS = "project_limits:\n  max_concurrent_stacks: 2\n"

# name -> (tracked text, local text, the setting left, the local path that stops it)
CASES = {
    "the same path with an equal value": (
        APP,
        "repos:\n  app:\n    path: ../app\n",
        PATH,
        PATH,
    ),
    "the same path with another value": (
        APP,
        "repos:\n  app:\n    path: ../other\n",
        PATH,
        PATH,
    ),
    "a key beneath a block": (
        LIMITS,
        "project_limits:\n  max_concurrent_stacks: 1\n",
        ("project_limits",),
        ("project_limits", "max_concurrent_stacks"),
    ),
    "an ancestor set to a scalar": (APP, "repos: 3\n", PATH, ("repos",)),
    "an ancestor set to a list": (APP, "repos:\n  app: [a, b]\n", PATH, ("repos", "app")),
    "an ancestor set to null": (APP, "repos:\n  app:\n", PATH, ("repos", "app")),
}


@pytest.mark.parametrize("name", CASES)
def test_a_conflicting_setting_is_left_and_reported(name: str, tmp_path: Path) -> None:
    base, local, left, local_path = CASES[name]

    result = move_machine_settings(base, request(tmp_path, local))

    assert result.conflicts == (Conflict(path=left, local_path=local_path),)
    assert result.moved == ()
    assert result.text == base
    assert result.local_text == local


def test_a_sibling_local_key_is_not_a_conflict(tmp_path: Path) -> None:
    local = "repos:\n  app:\n    account: personal\n"

    result = move_machine_settings(APP, request(tmp_path, local))

    assert result.conflicts == ()
    assert result.moved == (PATH,)


def test_the_other_settings_still_move(tmp_path: Path) -> None:
    base = APP + "planning:\n  worktree_root: /opt/trees\n"
    local = "planning:\n  worktree_root: /opt/mine\n"

    result = move_machine_settings(base, request(tmp_path, local))

    assert result.conflicts == (
        Conflict(path=("planning", "worktree_root"), local_path=("planning", "worktree_root")),
    )
    assert result.moved == (PATH,)
    assert result.text == (
        "repos:\n  app:\n    slug: example/app\nplanning:\n  worktree_root: /opt/trees\n"
    )
    assert result.local_text == (
        "planning:\n  worktree_root: /opt/mine\nrepos:\n  app:\n    path: ../app\n"
    )
    assert merged(result.text, result.local_text) == merged(base, local)
