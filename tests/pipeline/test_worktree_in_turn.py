"""The worktree wrapper `build_runner` assigns to the runner carries a killed run's
edits through: it forwards `allow_dirty`, and every wrapper keeps its protocol's
parameters. The wiring is the real one over a real git repository."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.stack_runner import RunStatus, UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_runner
from agent_build_kit.pipeline.workspaces import DirtyWorktree
from tests.conftest import make_installation
from tests.factories import unit
from tests.graph.test_resume_over_leftovers import STRAY, UNIT, killed_in
from tests.graph_driver import tick
from tests.leftovers_driver import LEFTOVER, Habitat, Hands

BASE = "origin/main"


def wired_runner(tmp_path: Path, habitat: Habitat) -> UnitRunner:
    """The real runner for a unit in `app`, whose checkout and worktrees are the habitat's."""
    installation = make_installation(
        tmp_path / "planning",
        repos={"app": {"path": str(habitat.repo), "slug": "example/app"}},
        planning=dict(worktree_root=str(habitat.trees)),
    )
    return build_runner(
        unit(),
        store=UnitStore(tmp_path / "units.json"),
        installation=installation,
        log=lambda _: None,
    )


def missing_parameters(wrapper: Callable[..., Any], protocol: type) -> list[str]:
    """The parameters of `protocol.__call__` that `wrapper` does not accept under the
    same name and default. A catch-all in the protocol is named, as the check cannot
    judge it."""
    declared = list(inspect.signature(protocol.__call__).parameters.values())[1:]
    accepted = inspect.signature(wrapper).parameters
    missing: list[str] = []
    for parameter in declared:
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            missing.append(f"{parameter.name} (a catch-all the check cannot judge)")
        elif (
            parameter.name not in accepted or accepted[parameter.name].default != parameter.default
        ):
            missing.append(parameter.name)
    return missing


def protocol_fields() -> dict[str, type]:
    """The runner's fields typed as a protocol with a call, by field name."""
    return {
        name: field.annotation
        for name, field in UnitRunner.model_fields.items()
        if inspect.isclass(field.annotation) and getattr(field.annotation, "_is_protocol", False)
    }


def test_a_dirty_worktree_is_returned_when_allowed_and_refused_otherwise(tmp_path: Path) -> None:
    runner = wired_runner(tmp_path, Habitat(tmp_path, Hands()))
    tree = runner.worktree(unit(), BASE)
    (tree / STRAY).write_text("left by a killed run\n")

    assert runner.worktree(unit(), BASE, allow_dirty=True) == tree
    with pytest.raises(DirtyWorktree):
        runner.worktree(unit(), BASE)


def test_a_unit_resumed_over_leftovers_through_the_wiring_is_not_failed(tmp_path: Path) -> None:
    habitat, recorder = killed_in(tmp_path, "implement")
    overrides: dict[str, Any] = habitat.overrides()
    overrides["worktree"] = wired_runner(tmp_path, habitat).worktree

    outcome = tick(tmp_path, recorder, **overrides)

    assert "TypeError" not in outcome.detail
    assert outcome.status == RunStatus.OPEN
    assert recorder.store.get(UNIT).state != "failed"
    assert LEFTOVER in habitat.files_in("feat:")


def test_a_wrapper_that_omits_a_protocol_parameter_is_reported_by_name(tmp_path: Path) -> None:
    runner = wired_runner(tmp_path, Habitat(tmp_path, Hands()))

    def worktree_in_turn(unit: Any, base: str) -> Path:
        raise NotImplementedError

    protocol = protocol_fields()["worktree"]
    assert missing_parameters(worktree_in_turn, protocol) == ["allow_dirty"]
    assert missing_parameters(runner.worktree, protocol) == []


def test_every_wrapper_build_runner_assigns_keeps_its_protocols_parameters(tmp_path: Path) -> None:
    runner = wired_runner(tmp_path, Habitat(tmp_path, Hands()))
    fields = protocol_fields()
    assert "worktree" in fields

    dropped = {
        name: missing
        for name, protocol in fields.items()
        if (missing := missing_parameters(getattr(runner, name), protocol))
    }

    assert dropped == {}
