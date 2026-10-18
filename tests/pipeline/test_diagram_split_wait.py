"""The graph draws a unit a held e2e-test split keeps from starting as waiting, and says so in
the legend and the state description (spec: split-start-gate)."""

from __future__ import annotations

import re

from agent_build_kit.pipeline.diagram import render_markdown, render_mermaid
from agent_build_kit.pipeline.vocabulary import effective_state, state_label
from tests.factories import new_unit


def classes_of(diagram: str) -> list[str]:
    return re.findall(r"^\s+class \S+ (\S+)$", diagram, flags=re.MULTILINE)


def test_a_gated_unit_is_drawn_in_the_class_of_a_blocked_unit() -> None:
    units = [new_unit("gated/1", split="acp"), new_unit("free/1")]

    drawn = render_mermaid(units, gated={"gated/1"})

    assert classes_of(drawn) == ["planned", "blocked"]


def test_a_gated_unit_reads_blocked_and_the_same_unit_ungated_reads_planned() -> None:
    unit = new_unit("gated/1", split="acp")

    assert effective_state(unit, [unit], gated={"gated/1"}) == "blocked"
    assert effective_state(unit, [unit]) == "planned"


def test_the_state_description_says_a_unit_may_wait_on_a_held_split() -> None:
    label = state_label("blocked")

    assert label is not None
    assert "held e2e-test split" in label.description


def test_the_legend_names_the_held_split_and_a_page_with_no_gated_unit_does_not() -> None:
    units = [new_unit("gated/1", split="acp"), new_unit("free/1")]

    with_gate = render_markdown(units, gated={"gated/1"})
    without = render_markdown(units)

    assert "held e2e-test split" in with_gate.split("## Legend")[1]
    assert "e2e-test split" not in without, "the page is what it was before this change"
