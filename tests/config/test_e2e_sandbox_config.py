"""`repos.<name>.tests.e2e_sandbox`: what an e2e-test step may touch beyond a unit-test step's
policy (spec: sandbox-e2e-policy)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import config
from agent_build_kit.config import ConfigError

REPO = "repos:\n  app:\n    path: /srv/app\n    slug: example/app\n"


def load(path: Path) -> Any:
    """The loaded configuration, untyped: the `e2e_sandbox` block is what these tests add."""
    return config.load(path)


def write(tmp_path: Path, block: str = "") -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text(REPO + block)
    return path


def test_the_four_lists_load_and_hold_what_is_written(tmp_path: Path) -> None:
    loaded = load(
        write(
            tmp_path,
            "    tests:\n      e2e_sandbox:\n"
            "        read: [/srv/fixtures]\n"
            "        write: [/srv/run]\n"
            "        hosts: [registry.example.test]\n"
            "        ports: [5432, 6379]\n",
        )
    )

    given = loaded.repos["app"].tests.e2e_sandbox
    assert given.read == ["/srv/fixtures"]
    assert given.write == ["/srv/run"]
    assert given.hosts == ["registry.example.test"]
    assert given.ports == [5432, 6379]


def test_a_repo_with_no_block_has_four_empty_lists(tmp_path: Path) -> None:
    loaded = load(write(tmp_path, "    tests:\n      e2e_marker: local_stack\n"))

    given = loaded.repos["app"].tests.e2e_sandbox
    assert (given.read, given.write, given.hosts, given.ports) == ([], [], [], [])


def test_an_unknown_key_fails_at_load_and_names_it(tmp_path: Path) -> None:
    ok = write(tmp_path, "    tests:\n      e2e_sandbox:\n        ports: [5432]\n")
    assert load(ok).repos["app"].tests.e2e_sandbox.ports == [5432]

    bad = write(
        tmp_path, "    tests:\n      e2e_sandbox:\n        ports: [5432]\n        sockets: [x]\n"
    )
    with pytest.raises(ConfigError, match="sockets"):
        load(bad)


def test_a_port_that_is_not_a_number_fails_at_load(tmp_path: Path) -> None:
    ok = write(tmp_path, "    tests:\n      e2e_sandbox:\n        ports: [5432]\n")
    assert load(ok).repos["app"].tests.e2e_sandbox.ports == [5432]

    bad = write(tmp_path, "    tests:\n      e2e_sandbox:\n        ports: [postgres]\n")
    with pytest.raises(ConfigError, match="ports"):
        load(bad)
