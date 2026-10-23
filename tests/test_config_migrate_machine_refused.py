"""What lines cannot edit is refused, naming the key and the file, and nothing is returned."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config_migrate import ConfigMigrateError
from agent_build_kit.config_migrate_machine import move_machine_settings
from tests.config_migrate_machine_support import request

APP = "repos:\n  app:\n    slug: example/app\n    path: ../app\n"
PATH = "repos.app.path"

# name -> (tracked text, local text, the key named, the file named)
CASES = {
    "an anchor on the entry": (
        "repos:\n  app: &app\n    slug: example/app\n    path: ../app\n",
        None,
        PATH,
        "abk.yaml",
    ),
    "an alias in a moved line": (
        "cap: &cap 2\nproject_limits:\n  max_concurrent_stacks: *cap\n",
        None,
        "project_limits",
        "abk.yaml",
    ),
    "a flow-style parent": ("repos: {app: {path: ../app}}\n", None, PATH, "abk.yaml"),
    "a merge key in a parent": (
        "common: &common\n  slug: example/app\nrepos:\n  app:\n    <<: *common\n    path: ../app\n",
        None,
        PATH,
        "abk.yaml",
    ),
    "a setting that exists only through a merge key": (
        "common: &common\n  path: ../app\nrepos:\n  app:\n    <<: *common\n",
        None,
        PATH,
        "abk.yaml",
    ),
    "several documents": (APP + "---\nother: 1\n", None, "abk.yaml", "abk.yaml"),
    "a local text that does not parse": (APP, "repos: [\n", PATH, "abk.local.yaml"),
    "a local text of several documents": (
        APP,
        "other: 1\n---\nmore: 2\n",
        PATH,
        "abk.local.yaml",
    ),
    "a local text that is not a mapping": (APP, "- a\n- b\n", PATH, "abk.local.yaml"),
    "a flow-style place in the local text": (
        APP,
        "repos: {app: {account: personal}}\n",
        PATH,
        "abk.local.yaml",
    ),
    "an anchored place in the local text": (
        APP,
        "repos: &repos\n  app:\n    account: personal\n",
        PATH,
        "abk.local.yaml",
    ),
    "a merge key in the place in the local text": (
        APP,
        "common: &common\n  account: personal\nrepos:\n  app:\n    <<: *common\n",
        PATH,
        "abk.local.yaml",
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_each_is_refused_with_the_key_and_the_file(name: str, tmp_path: Path) -> None:
    base, local, key, file = CASES[name]

    with pytest.raises(ConfigMigrateError) as refused:
        move_machine_settings(base, request(tmp_path, local))

    assert key in str(refused.value), str(refused.value)
    assert file in str(refused.value), str(refused.value)


def test_a_flow_style_value_on_one_line_moves_as_written(tmp_path: Path) -> None:
    base = (
        "runtimes:\n  claude:\n    command: [/opt/c/bin/claude, -p]\n"
        "    models:\n      fast: small\n"
    )

    result = move_machine_settings(base, request(tmp_path))

    assert result.text == "runtimes:\n  claude:\n    models:\n      fast: small\n"
    assert result.local_text == "runtimes:\n  claude:\n    command: [/opt/c/bin/claude, -p]\n"


def test_a_local_text_is_not_read_when_nothing_moves(tmp_path: Path) -> None:
    local = "repos: [\n"
    base = "repos:\n  app:\n    slug: example/app\n"

    result = move_machine_settings(base, request(tmp_path, local))

    assert result.moved == ()
    assert result.conflicts == ()
    assert result.text == base
    assert result.local_text == local
