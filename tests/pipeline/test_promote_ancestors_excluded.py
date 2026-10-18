"""A waiter the round leaves out lends no priority, and lends it again once it is no longer left
out (spec: split-start-gate)."""

from agent_build_kit.pipeline.planner import promote_ancestors
from tests.pipeline.test_promote_ancestors import catalog, result, stored


def test_a_waiter_in_excluded_gives_its_prerequisite_nothing(tmp_path) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)))

    promote_ancestors(store, catalog(3, 1), ["c/2"])

    assert result(store, 1) == (3, "")


def test_the_promotion_comes_back_the_next_pass_when_the_waiter_is_no_longer_excluded(
    tmp_path,
) -> None:
    store = stored(tmp_path, (1, ()), (2, (1,)))
    promote_ancestors(store, catalog(3, 1), ["c/2"])

    promote_ancestors(store, catalog(3, 1), [])

    assert result(store, 1) == (1, "c/2")
