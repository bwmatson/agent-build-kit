"""`review.unsplittable` chooses what happens to a unit over its ceiling that cannot be split
(spec: unsplittable-size)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.config import load
from tests.review_config import workspace


def test_the_setting_defaults_to_opening_a_pull_request() -> None:
    assert workspace().review.unsplittable == "open_pr"
    assert workspace({}).review.unsplittable == "open_pr"


def test_hold_is_accepted() -> None:
    assert workspace({"unsplittable": "hold"}).review.unsplittable == "hold"


@pytest.mark.parametrize("value", ["wait", "ask", "OPEN_PR", True, 1, ""])
def test_nothing_else_is_accepted(value: object) -> None:
    assert workspace({"unsplittable": "open_pr"}).review.unsplittable == "open_pr"
    with pytest.raises(ValidationError, match="unsplittable"):
        workspace({"unsplittable": value})


def test_the_setting_loads_from_abk_yaml(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(
        "repos:\n  app:\n    path: /work/app\n    slug: example/app\n"
        "review:\n  unsplittable: hold\n"
    )

    assert load(path).review.unsplittable == "hold"
