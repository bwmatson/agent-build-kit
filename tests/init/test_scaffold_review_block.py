"""A drafted abk.yaml shows the `review` section commented out (spec: review-policy)."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit.config import RepoConfig, WorkspaceConfig, load
from agent_build_kit.init.scaffold import dump_with_notes

KEYS = (
    "# review:",
    "#   enabled: false",
    "#   protected_paths: []",
    "#   protected_defaults: true",
    "#   classes: {}",
    "#   auto_land: {min_samples: 20, min_clean_rate: 0.95, classes: []}",
    "#   audit: {sample_rate: 0.1}",
    "#   demotion: {window: 30, min_agreement: 0.9}",
)


def drafted(tmp_path: Path) -> str:
    config = WorkspaceConfig(repos={"app": RepoConfig(path=tmp_path / "app", slug="example/app")})
    return dump_with_notes(config)


def test_a_drafted_file_carries_the_commented_review_block(tmp_path: Path) -> None:
    lines = drafted(tmp_path).splitlines()

    for key in KEYS:
        assert key in lines
    assert "review" not in yaml.safe_load("\n".join(lines)), "every line of the block is a comment"


def test_a_drafted_file_still_loads_with_review_off_and_every_default(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(drafted(tmp_path))

    loaded = load(path)

    assert loaded.review.model_dump() == WorkspaceConfig().review.model_dump()
    assert loaded.review.model_dump()["enabled"] is False
    assert loaded.review.model_dump()["auto_land"] == {
        "min_samples": 20,
        "min_clean_rate": 0.95,
        "allow_deferred_e2e": False,
        "classes": [],
    }
