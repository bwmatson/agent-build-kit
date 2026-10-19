"""An e2e-test run leaves out the tests carrying an unavailable value's marker, in every
branch of the selection (spec: e2e-dimensions)."""

from __future__ import annotations

import pytest

from agent_build_kit.config import E2eSplit
from agent_build_kit.pipeline.e2e import build_selection
from agent_build_kit.profiles.python_uv import PROFILE

MARKER = "local_stack"
OTEL = "telemetry_otel"
SPLITS = (
    E2eSplit(name="acp", marker="runtime_acp"),
    E2eSplit(name="claude_code", marker="runtime_claude_code"),
    E2eSplit(name="otel", marker=OTEL),
    E2eSplit(name="rest"),
)


def text(**kwargs: object) -> str:
    return PROFILE.expression(MARKER, build_selection(MARKER, SPLITS, **kwargs))  # type: ignore[arg-type]


def test_the_default_run_leaves_out_the_unavailable_marker() -> None:
    assert text(unavailable=[OTEL]) == f"{MARKER} and not {OTEL}"


def test_a_held_run_leaves_out_the_held_and_the_unavailable() -> None:
    expression = text(held=["acp"], unavailable=[OTEL])

    assert "not runtime_acp" in expression
    assert f"not {OTEL}" in expression


def test_rest_held_does_not_bring_the_unavailable_marker_back() -> None:
    selection = build_selection(MARKER, SPLITS, held=["rest"], unavailable=[OTEL])

    assert OTEL not in selection.any_of
    assert not selection.empty
    assert set(selection.any_of) == {"runtime_acp", "runtime_claude_code"}


def test_rest_held_leaves_out_an_unavailable_marker_that_is_no_split_marker() -> None:
    splits = (E2eSplit(name="acp", marker="runtime_acp"), E2eSplit(name="rest"))

    expression = PROFILE.expression(
        MARKER, build_selection(MARKER, splits, held=["rest"], unavailable=[OTEL])
    )

    assert "runtime_acp" in expression
    assert f"not {OTEL}" in expression


def test_a_split_run_alone_still_leaves_out_the_unavailable_marker() -> None:
    expression = text(only="acp", unavailable=["runtime_claude_code"])

    assert "runtime_acp" in expression
    assert "not runtime_claude_code" in expression


def test_rest_alone_leaves_out_the_unavailable_marker() -> None:
    assert "not telemetry_local" in text(only="rest", unavailable=["telemetry_local"])


def test_a_split_whose_only_marker_is_unavailable_is_empty() -> None:
    selection = build_selection(MARKER, SPLITS, only="otel", unavailable=[OTEL])

    assert selection.empty
    with pytest.raises(ValueError, match="nothing to run"):
        PROFILE.expression(MARKER, selection)


def test_rest_held_with_every_declared_marker_unavailable_is_empty() -> None:
    selection = build_selection(
        MARKER,
        SPLITS,
        held=["rest"],
        unavailable=["runtime_acp", "runtime_claude_code", OTEL],
    )

    assert selection.empty
