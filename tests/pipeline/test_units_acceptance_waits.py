"""An acceptance or narrow unit waits for every earlier unit of its change.

The wait is computed from the change's units each time, not from stored edges:
the unit stores only the last unit of its chain, and still waits for a unit two
places before it that was sent back, for an independent unit and for an earlier
unit in another repository. It adds waits only, so the unit's base, depth and open
parents are what its stored dependencies alone give, and a unit with no flag
follows the chain.
"""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.units import (
    FAILED,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    UnitState,
    base_of,
    depth_of,
    open_parents,
    second_open_parents,
    waiting_on,
)
from tests.factories import started_ids
from tests.factories import stored_unit as unit

CHAIN = ("feature/1", "feature/2", "feature/3")
ACCEPTANCE = "feature/5"


def chain_graph(*, flag: str = "acceptance", first: UnitState = PLANNED):
    """A chain of three (the third in review, the first sent back), an independent
    unit, a unit of another change, and a flagged unit storing only the chain's end
    and the independent unit."""
    return [
        unit("feature/1", change="feature", state=first),
        unit("feature/2", change="feature", depends_on=("feature/1",), state=IN_REVIEW),
        unit("feature/3", change="feature", depends_on=("feature/2",), state=IN_REVIEW),
        unit("feature/4", change="feature", state=PLANNED),
        unit("other/1", change="other", state=PLANNED),
        unit(
            ACCEPTANCE,
            change="feature",
            depends_on=("feature/3",),
            flag=flag,
        ),
    ]


def waits(graph, uid: str = ACCEPTANCE) -> set[str]:
    return {w.id for w in waiting_on(next(u for u in graph if u.id == uid), graph)}


def replaced(graph, uid: str, **update):
    return [u.model_copy(update=update) if u.id == uid else u for u in graph]


@pytest.mark.parametrize("flag", ["acceptance", "narrow"])
def test_flagged_unit_waits_for_the_unit_sent_back_and_the_independent_one(flag: str) -> None:
    """Not for the other change's unit, the unit the plan dropped, or one numbered after it."""
    graph = [
        *chain_graph(flag=flag),
        unit("feature/6", change="feature", state=PLANNED),
        unit("feature/0", change="feature", state=UnitState.UNPLANNED),
    ]

    assert waits(graph) == {"feature/1", "feature/4"}
    assert ACCEPTANCE not in started_ids(graph, slots=5)


@pytest.mark.parametrize("flag", ["acceptance", "narrow"])
@pytest.mark.parametrize("settled", [IN_REVIEW, MERGED, SATISFIED])
def test_the_wait_ends_when_each_earlier_unit_is_reviewed_merged_or_satisfied(
    flag: str, settled: UnitState
) -> None:
    graph = chain_graph(flag=flag)
    assert waits(graph) == {"feature/1", "feature/4"}

    graph = replaced(replaced(graph, "feature/1", state=settled), "feature/4", state=settled)

    assert waits(graph) == set()


@pytest.mark.parametrize("state", [PLANNED, RUNNING, FAILED])
def test_an_earlier_unit_not_yet_reviewed_holds_the_unit(state: UnitState) -> None:
    graph = replaced(chain_graph(), "feature/1", state=state)

    assert "feature/1" in waits(graph)


def test_an_earlier_unit_in_another_repository_holds_the_unit_until_merged() -> None:
    graph = chain_graph(first=MERGED)
    graph = replaced(graph, "feature/4", state=IN_REVIEW, repo="platform")

    assert waits(graph) == {"feature/4"}
    assert waits(replaced(graph, "feature/4", state=MERGED)) == set()


def test_a_satisfied_earlier_unit_in_another_repository_holds_the_unit_until_landed() -> None:
    base = replaced(chain_graph(first=MERGED), "feature/4", state=MERGED)
    behind = unit("other/9", change="other", repo="platform", state=IN_REVIEW)

    def satisfied(*depends_on: str):
        return unit(
            "feature/0",
            change="feature",
            repo="platform",
            state=SATISFIED,
            depends_on=depends_on,
        )

    assert waits([*base, satisfied()]) == set()
    assert waits([*base, behind, satisfied("other/9")]) == {"feature/0"}
    merged = behind.model_copy(update={"state": MERGED})
    assert waits([*base, merged, satisfied("other/9")]) == set()


def test_the_rule_adds_waits_only() -> None:
    graph = chain_graph(first=MERGED)
    graph = replaced(graph, "feature/4", state=IN_REVIEW)
    plain = replaced(graph, ACCEPTANCE, flag="")
    flagged = graph[-1]
    bare = plain[-1]

    assert base_of(flagged, graph) == base_of(bare, plain)
    assert depth_of(flagged, graph) == depth_of(bare, plain)
    assert open_parents(flagged, graph) == open_parents(bare, plain)
    assert second_open_parents(flagged, graph) == second_open_parents(bare, plain)
    # And with a wait in force, the four are still what the stored edges give.
    held = replaced(graph, "feature/4", state=PLANNED)
    assert waits(held) == {"feature/4"}
    assert base_of(held[-1], held) == base_of(bare, plain)
    assert open_parents(held[-1], held) == open_parents(bare, plain)
    assert depth_of(held[-1], held) == depth_of(bare, plain)
    assert second_open_parents(held[-1], held) == second_open_parents(bare, plain)


@pytest.mark.parametrize("flag", ["", "contract"])
def test_an_unflagged_unit_follows_the_chain(flag: str) -> None:
    """The unit's parent is in review and the grandparent is sent back: a plain chain
    is ready, where the same unit flagged is not."""
    graph = chain_graph(flag=flag)
    flagged = chain_graph()

    assert waits(flagged) != set()
    assert waits(graph) == set()
    assert ACCEPTANCE in started_ids(graph, slots=5)
