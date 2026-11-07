"""The default of `repos.<name>.tests.e2e_marker` (spec: test-markers)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit import config

REPO = "repos:\n  app:\n    path: /srv/app\n    slug: example/app\n"


def load(tmp_path: Path, block: str = "") -> Any:
    path = tmp_path / "abk.yaml"
    path.write_text(REPO + block)
    return config.load(path)


def test_a_repo_that_sets_no_marker_selects_e2e_tests_by_e2e(tmp_path: Path) -> None:
    assert load(tmp_path).repos["app"].tests.e2e_marker == "e2e"


def test_a_repo_that_names_its_own_marker_keeps_the_default_for_the_rest(tmp_path: Path) -> None:
    loaded = load(tmp_path, "    tests:\n      e2e_marker: slow\n")

    assert loaded.repos["app"].tests.e2e_marker == "slow"
    assert config.TestsConfig().e2e_marker == "e2e"
