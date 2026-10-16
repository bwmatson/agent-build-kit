"""The one builder of the tier 2 selection over a repo's declared splits (spec: tier2-splits)."""

from __future__ import annotations

import pytest

from agent_build_kit.config import Tier2Split
from agent_build_kit.pipeline.e2e import build_selection
from agent_build_kit.profiles.python_uv import PROFILE

MARKER = "local_stack"
SPLITS = (
    Tier2Split(name="acp", marker="runtime_acp"),
    Tier2Split(name="claude_code", marker="runtime_claude_code"),
    Tier2Split(name="rest"),
)


def text(**kwargs: object) -> str:
    return PROFILE.expression(MARKER, build_selection(MARKER, SPLITS, **kwargs))  # type: ignore[arg-type]


def test_nothing_held_gives_the_marker_alone() -> None:
    selection = build_selection(MARKER, SPLITS)

    assert PROFILE.expression(MARKER, selection) == MARKER
    assert selection.left_out == ()
    assert selection.only is None
    assert not selection.empty


def test_each_held_split_is_left_out() -> None:
    selection = build_selection(MARKER, SPLITS, held=["claude_code", "acp"])

    assert selection.left_out == ("acp", "claude_code")
    assert (
        PROFILE.expression(MARKER, selection)
        == "local_stack and not runtime_acp and not runtime_claude_code"
    )


def test_one_split_asked_for_alone_is_the_marker_and_its_selector() -> None:
    selection = build_selection(MARKER, SPLITS, only="acp")

    assert selection.only == "acp"
    assert PROFILE.expression(MARKER, selection) == "local_stack and runtime_acp"


def test_rest_alone_leaves_out_every_declared_split() -> None:
    selection = build_selection(MARKER, SPLITS, only="rest")

    assert selection.only == "rest"
    assert selection.left_out == ("acp", "claude_code")
    assert (
        PROFILE.expression(MARKER, selection)
        == "local_stack and not runtime_acp and not runtime_claude_code"
    )


def test_rest_held_keeps_only_the_declared_splits() -> None:
    selection = build_selection(MARKER, SPLITS, held=["rest"])

    assert "rest" in selection.left_out
    assert not selection.empty
    assert (
        PROFILE.expression(MARKER, selection)
        == "local_stack and (runtime_acp or runtime_claude_code)"
    )


def test_every_split_held_selects_nothing_and_says_so() -> None:
    selection = build_selection(MARKER, SPLITS, held=["acp", "claude_code", "rest"])

    assert selection.empty


def test_a_repo_with_no_declared_split_has_rest_alone() -> None:
    selection = build_selection(MARKER, (Tier2Split(name="rest"),))

    assert PROFILE.expression(MARKER, selection) == MARKER


def test_an_undeclared_held_name_is_refused_naming_the_splits_there_are() -> None:
    with pytest.raises(ValueError, match="nonesuch") as raised:
        build_selection(MARKER, SPLITS, held=["nonesuch"])

    assert "acp" in str(raised.value)
    assert "rest" in str(raised.value)


def test_an_undeclared_only_name_is_refused_naming_the_splits_there_are() -> None:
    with pytest.raises(ValueError, match="nonesuch") as raised:
        build_selection(MARKER, SPLITS, only="nonesuch")

    assert "claude_code" in str(raised.value)


def test_a_held_split_is_never_run_alone() -> None:
    with pytest.raises(ValueError, match="acp"):
        build_selection(MARKER, SPLITS, held=["acp"], only="acp")
    with pytest.raises(ValueError, match="rest"):
        build_selection(MARKER, SPLITS, held=["rest"], only="rest")


def test_the_same_inputs_always_give_the_same_selection() -> None:
    first = build_selection(MARKER, SPLITS, held=["claude_code", "acp"])
    again = build_selection(MARKER, SPLITS, held=["acp", "claude_code", "acp"])

    assert first == again
    assert text(held=["acp"]) == text(held=["acp"])
