"""The graph labels a unit parked for the network apart from one parked for the model service."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.diagram import render_mermaid
from tests.factories import stored_unit


def parked(cause: str):
    entry = {
        "state": "planned",
        "at": "2030-01-01T09:00:00+00:00",
        "note": "EAI_AGAIN",
        "cause": cause,
    }
    return stored_unit(
        "c/1", state="planned", branch="spec/c/1", step="implement", history=(entry,)
    )


@pytest.mark.parametrize(
    ("cause", "label"),
    [
        ("network_unavailable", "waiting for the network"),
        ("service_unavailable", "waiting for the model service"),
    ],
)
def test_a_parked_unit_is_labelled_by_what_it_waits_for(cause: str, label: str) -> None:
    assert label in render_mermaid([parked(cause)])


def test_the_two_causes_are_labelled_differently() -> None:
    assert render_mermaid([parked("network_unavailable")]) != render_mermaid(
        [parked("service_unavailable")]
    )


def test_a_parked_unit_shows_its_step_and_when_it_may_run_again() -> None:
    label = render_mermaid([parked("network_unavailable")])

    assert "waiting for the network at implement, retry after 09:01 UTC" in label
