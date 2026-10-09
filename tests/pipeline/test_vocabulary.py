"""One vocabulary for the graph and the labels.

The diagram and a pull request's labels name and colour the same states. They
read one definition, and these tests are what stops a new state leaving the two
surfaces disagreeing about the same unit.
"""

import re

from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL, REWORK_LABEL
from agent_build_kit.pipeline.vocabulary import (
    INSTRUCTION_PREFIX,
    STATES,
    UNLABELLED,
    change_label,
    state_label,
    state_label_names,
)
from tests.factories import stored_unit

EVERY_STATE = {
    "planned",
    "blocked",
    "running",
    "rebasing",
    "reworking",
    "paused_rework",
    "held",
    "in_review",
    "checking",
    "merged",
    "satisfied",
    "closed",
    "failed",
    "unplanned",
}


def test_the_vocabulary_holds_every_state_the_graph_can_draw() -> None:
    assert set(STATES) == EVERY_STATE


def test_every_state_has_a_label_named_and_coloured_as_the_graph_or_is_unlabelled() -> None:
    assert STATES
    for key, style in STATES.items():
        label = state_label(key)
        if key in UNLABELLED:
            assert label is None, f"{key} is documented as unlabelled"
            continue
        assert label is not None, f"{key} has neither a label nor a place on the unlabelled list"
        assert label.name == style.name
        # The outline, not the pale fill: a host paints a label as a solid chip.
        assert label.color == style.stroke.removeprefix("#")
        assert label.description, "a label says what it means"


def test_the_states_the_host_shows_or_that_have_no_pull_request_are_unlabelled() -> None:
    assert {"merged", "closed", "unplanned"} <= UNLABELLED
    assert UNLABELLED <= EVERY_STATE


def test_the_states_derived_from_history_each_get_their_own_label() -> None:
    labels = [state_label(key) for key in ("blocked", "paused_rework")]

    names = [label.name for label in labels if label is not None]

    assert len(names) == 2, "each of the two has a label"
    assert len(set(names)) == 2, "waiting and stopped before a rework must not share one"
    planned = state_label("planned")
    assert planned is not None
    assert planned.name not in names


def test_a_state_is_named_as_the_graph_writes_it() -> None:
    assert STATES["paused_rework"].name == "paused-rework"
    assert STATES["in_review"].name == "in-review"


def test_no_state_label_reads_as_an_instruction() -> None:
    names = state_label_names()

    assert names
    assert names == {label.name for key in STATES if (label := state_label(key))}
    assert not any(name.startswith(INSTRUCTION_PREFIX) for name in names)


def test_the_diagram_is_drawn_from_the_vocabulary_unchanged() -> None:
    """Every class the diagram defines, and only those, in the colours the
    vocabulary holds."""
    assert STATES
    lines = render_mermaid([stored_unit()]).splitlines()

    defined = {line.split()[1] for line in lines if line.strip().startswith("classDef")}
    assert defined == EVERY_STATE
    for key, style in STATES.items():
        expected = f"    classDef {key} fill:{style.fill},stroke:{style.stroke},color:{style.text}"
        if style.extra:
            expected += f",{style.extra}"
        assert expected in lines


def test_a_node_reads_as_its_state_is_named_in_the_vocabulary() -> None:
    parent = stored_unit("add-marker/1", state="running")
    child = stored_unit(
        "add-marker/2",
        depends_on=("add-marker/1",),
        state="planned",
        history=({"state": "planned", "at": "t", "note": "words", "cause": "upstream_went_back"},),
    )
    reviewing = stored_unit("add-marker/3", state="in_review", pr=3)

    nodes = {
        line.strip().split("[")[0]: line
        for line in render_mermaid([parent, child, reviewing]).splitlines()
    }

    assert f"· {STATES['paused_rework'].name}" in nodes["add_marker_2"]
    assert f"· {STATES['in_review'].name}" in nodes["add_marker_3"]


def test_the_colours_are_the_ones_the_graph_has_always_used() -> None:
    assert STATES["running"].stroke == "#d97706"
    assert STATES["in_review"].stroke == "#2563eb"
    assert STATES["paused_rework"].extra == "stroke-dasharray:3 3"
    assert STATES["failed"].extra == "stroke-width:3px"
    line = "    classDef running fill:#fef3c7,stroke:#d97706,color:#451a03"
    assert line in render_mermaid([stored_unit()]).splitlines()


PLAIN_NAME = re.compile(r"[a-z0-9-]{1,50}")


def test_a_change_named_with_capitals_and_punctuation_gives_a_lowercase_dash_label() -> None:
    assert change_label("Wave_2: Close Out!").name == "change-wave-2-close-out"


def test_a_name_already_plain_is_unchanged() -> None:
    assert change_label("add-marker").name == "change-add-marker"


def test_a_long_name_is_cut_to_fifty_without_a_trailing_dash() -> None:
    name = "a" * 42 + "-" + "b" * 20  # "change-" + 42 a's puts the dash at character 50
    label = change_label(name).name

    assert len(label) <= 50
    assert not label.endswith("-")
    assert PLAIN_NAME.fullmatch(label)


def test_every_label_the_pipeline_writes_is_a_plain_name() -> None:
    names = [
        *state_label_names(),
        HOLD_LABEL,
        REWORK_LABEL,
        *(change_label(c).name for c in ("add-marker", "Wave_2: Close Out!", "x" * 80, "a.b c")),
    ]

    assert names
    assert all(PLAIN_NAME.fullmatch(name) for name in names), names
