"""`repos.<name>.tests.workers` and `tests.max_workers`, the worker count of the profile's
test runs (spec: testmon-selection-honours-markers)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import WorkspaceConfig


def load(**tests: Any) -> WorkspaceConfig:
    app: dict[str, Any] = {"path": "/work/app", "slug": "example/app", "tests": tests}
    return WorkspaceConfig.model_validate({"repos": {"app": app}})


def read(loaded: WorkspaceConfig) -> dict[str, Any]:
    return loaded.repos["app"].tests.model_dump()


def test_unset_they_are_auto_and_eight() -> None:
    tests = read(load())

    assert (tests["workers"], tests["max_workers"]) == ("auto", 8)


def test_a_positive_integer_and_auto_are_read_as_given() -> None:
    assert read(load(workers=4, max_workers=6))["workers"] == 4
    assert read(load(workers="auto", max_workers=6))["max_workers"] == 6


@pytest.mark.parametrize("workers", [0, -2, "many", "4", 1.5, None, []])
def test_workers_other_than_auto_or_a_positive_integer_is_refused(workers: Any) -> None:
    assert read(load(max_workers=6))["max_workers"] == 6

    with pytest.raises(ValidationError, match="workers"):
        load(workers=workers)


@pytest.mark.parametrize("max_workers", [0, -1, "auto", "8", 2.5, None])
def test_max_workers_other_than_a_positive_integer_is_refused(max_workers: Any) -> None:
    assert read(load(workers=4))["workers"] == 4

    with pytest.raises(ValidationError, match="max_workers"):
        load(max_workers=max_workers)
