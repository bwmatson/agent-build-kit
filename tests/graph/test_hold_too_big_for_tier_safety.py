"""The size step never holds a unit because something broke, and never runs with review off
(spec: hold-and-split). Each test first shows the step live, so it is the safety that is
measured and not an absent step."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.factories import activate_with, unit
from tests.graph.test_build_path import build, fresh
from tests.runner_fakes import Recorder

UNIT_ID = unit().id
CEILINGS = {"auto": 1000, "light": 800, "full": 500}


def run(tmp_path: Path, *, enabled: bool = True) -> Recorder:
    activate_with(review={"enabled": enabled, "ceilings": CEILINGS})
    tmp_path.mkdir(exist_ok=True)
    recorder = fresh(tmp_path)
    recorder.changed_lines = 2000  # over the buffered `full` ceiling of 600
    build(tmp_path, recorder)
    return recorder


def replace_compute_verdict(monkeypatch: pytest.MonkeyPatch, replacement: object) -> None:
    """Stand `replacement` where every module of the package that names `compute_verdict` has it,
    so the test does not depend on which module the review step calls it through."""
    for name, module in list(sys.modules.items()):
        if name.startswith("agent_build_kit") and hasattr(module, "compute_verdict"):
            monkeypatch.setattr(module, "compute_verdict", replacement)


def test_a_verdict_that_raises_is_logged_and_the_unit_goes_on_as_in_shadow_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = run(tmp_path / "live")
    assert held.store.get(UNIT_ID).cause == Cause.TOO_BIG_FOR_TIER

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the verdict broke")

    replace_compute_verdict(monkeypatch, broken)
    recorder = run(tmp_path / "broken")

    stored = recorder.store.get(UNIT_ID)
    assert stored.state == IN_REVIEW
    assert stored.cause != Cause.TOO_BIG_FOR_TIER
    assert any("the verdict broke" in line for line in recorder.logged), recorder.logged


def test_with_review_disabled_the_size_step_is_never_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = run(tmp_path / "on")
    assert held.store.get(UNIT_ID).cause == Cause.TOO_BIG_FOR_TIER
    asked: list[object] = []

    def spy(*args: object, **kwargs: object) -> None:
        asked.append(args)
        raise AssertionError("the verdict was computed with review disabled")

    replace_compute_verdict(monkeypatch, spy)
    recorder = run(tmp_path / "off", enabled=False)

    assert asked == []
    stored = recorder.store.get(UNIT_ID)
    assert stored.state == IN_REVIEW
    assert stored.split_request is None
