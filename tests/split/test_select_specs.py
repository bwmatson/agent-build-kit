"""Which main specs a split moves: those only moved changes wrote deltas for."""

import pytest

from agent_build_kit.split.select import SplitUsageError, plan_split
from tests.split_sources import source_installation, write_change, write_spec


def source_with_three_capabilities(tmp_path):
    source = source_installation(tmp_path)
    for capability in ("only-app", "both", "nobody"):
        write_spec(source, capability)
    write_change(source, "moves", ["app"], deltas=["only-app", "both"])
    write_change(source, "stays", ["lib"], deltas=["both"])
    return source


def test_a_spec_whose_only_delta_is_in_a_moved_change_moves(tmp_path):
    plan = plan_split(source_with_three_capabilities(tmp_path), "app")

    assert plan.specs_moved == ("only-app",)


def test_a_spec_with_deltas_in_a_moved_and_a_staying_change_is_shared_and_stays(tmp_path):
    plan = plan_split(source_with_three_capabilities(tmp_path), "app")

    assert plan.specs_shared == ("both",)
    assert "both" not in plan.specs_moved


def test_a_spec_no_change_touches_is_unowned_and_stays(tmp_path):
    plan = plan_split(source_with_three_capabilities(tmp_path), "app")

    assert plan.specs_unowned == ("nobody",)
    assert "nobody" not in plan.specs_moved


def test_an_archived_change_counts_as_an_owner(tmp_path):
    source = source_installation(tmp_path)
    write_spec(source, "history")
    write_change(source, "done", ["app"], archived="2026-01-02", deltas=["history"])
    write_change(source, "also-done", ["lib"], archived="2026-01-03", deltas=["history"])

    assert plan_split(source, "app").specs_shared == ("history",)


def test_a_named_spec_moves_when_nothing_owns_it(tmp_path):
    source = source_with_three_capabilities(tmp_path)

    plan = plan_split(source, "app", specs=["nobody"])

    assert plan.specs_moved == ("nobody", "only-app")


def test_a_name_that_is_no_capability_is_refused(tmp_path):
    source = source_with_three_capabilities(tmp_path)

    with pytest.raises(SplitUsageError, match="nothing-here"):
        plan_split(source, "app", specs=["nothing-here"])
