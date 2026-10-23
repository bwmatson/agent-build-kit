"""The move lifts a machine setting out of abk.yaml's text into abk.local.yaml's, by lines."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config_migrate_machine import move_machine_settings
from tests.config_migrate_machine_support import TILDE, merged, request

BASE = f"""\
repos:
  app:
    slug: example/app
    profile: python-uv
    # where the checkout is
    path: ../app  # on this disk
    deploy:
      ssh_key: {TILDE}.ssh/deploy
planning:  # the planning repo
  worktree_root: {TILDE}work/trees
project_limits:
  # at most
  max_concurrent_stacks: 2
  max_units_in_progress: 3  # per tick
verify:
  env:
    TOKEN:
      from: env-file
      file: {TILDE}.config/app/.env
      key: TOKEN
"""

NEW_BASE = """\
repos:
  app:
    slug: example/app
    profile: python-uv
    deploy: {}
planning: {}  # the planning repo
verify:
  env:
    TOKEN:
      from: env-file
      key: TOKEN
"""

NEW_LOCAL = f"""\
repos:
  app:
    # where the checkout is
    path: ../app  # on this disk
    deploy:
      ssh_key: {TILDE}.ssh/deploy
planning:
  worktree_root: {TILDE}work/trees
project_limits:
  # at most
  max_concurrent_stacks: 2
  max_units_in_progress: 3  # per tick
verify:
  env:
    TOKEN:
      file: {TILDE}.config/app/.env
"""


def test_the_settings_of_the_table_leave_the_tracked_text_for_a_new_local_text(
    tmp_path: Path,
) -> None:
    result = move_machine_settings(BASE, request(tmp_path))

    assert result.local_text == NEW_LOCAL
    assert result.text == NEW_BASE
    assert result.moved == (
        ("repos", "app", "path"),
        ("repos", "app", "deploy", "ssh_key"),
        ("planning", "worktree_root"),
        ("project_limits",),
        ("verify", "env", "TOKEN", "file"),
    )
    assert result.conflicts == ()
    assert merged(result.text, result.local_text) == merged(BASE, None)


def test_only_the_moved_key_leaves_an_entry(tmp_path: Path) -> None:
    base = (
        "repos:\n  app:\n    slug: example/app\n    account: personal\n    profile: python-uv\n"
        "    tests:\n      unit_test: pytest -q\n"
    )

    result = move_machine_settings(base, request(tmp_path))

    assert result.text == (
        "repos:\n  app:\n    slug: example/app\n    profile: python-uv\n"
        "    tests:\n      unit_test: pytest -q\n"
    )
    assert result.local_text == "repos:\n  app:\n    account: personal\n"


def test_comments_directly_above_a_key_move_and_a_blank_line_stops_them(tmp_path: Path) -> None:
    base = (
        "repos:\n  app:\n    slug: example/app\n    # stays, a blank line follows\n\n"
        "    # about the account\n    # in two lines\n    account: personal\n"
        "    # belongs to the profile\n    profile: python-uv\n"
    )

    result = move_machine_settings(base, request(tmp_path))

    assert result.text == (
        "repos:\n  app:\n    slug: example/app\n    # stays, a blank line follows\n\n"
        "    # belongs to the profile\n    profile: python-uv\n"
    )
    assert result.local_text == (
        "repos:\n  app:\n    # about the account\n    # in two lines\n    account: personal\n"
    )


def test_a_block_key_moves_with_every_nested_line_at_the_local_files_depth(
    tmp_path: Path,
) -> None:
    base = (
        "runtimes:\n  claude:\n    accounts:\n      personal:\n        config_dir: /opt/personal\n"
        "        label: mine\n    models:\n      fast: small\n"
    )
    local = "runtimes:\n    claude:\n        extra: 1\n"

    result = move_machine_settings(base, request(tmp_path, local))

    assert result.text == "runtimes:\n  claude:\n    models:\n      fast: small\n"
    assert result.local_text == (
        "runtimes:\n    claude:\n        extra: 1\n        accounts:\n          personal:\n"
        "            config_dir: /opt/personal\n            label: mine\n"
    )
    assert merged(result.text, result.local_text) == merged(base, local)
