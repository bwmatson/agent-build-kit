"""The one builder of the tier 2 marker expression (spec: tier2-runtime-variants)."""

from __future__ import annotations

import pytest

from agent_build_kit import runtimes
from agent_build_kit.pipeline.tier2 import tier2_selection
from agent_build_kit.runtimes import known_agents

MARKER = "local_stack"


def known() -> set[str]:
    return {*runtimes.names(), known_agents.RUNTIME_NAME}


def test_nothing_blocked_gives_the_marker_alone() -> None:
    selection = tier2_selection(MARKER, [])

    assert selection.expression == MARKER
    assert selection.left_out == ()
    assert selection.only is None


def test_each_blocked_runtime_is_left_out_by_its_tag() -> None:
    selection = tier2_selection(MARKER, ["claude_code", "acp"])

    assert selection.expression == "local_stack and not runtime_acp and not runtime_claude_code"
    assert selection.left_out == ("acp", "claude_code")


def test_one_runtime_asked_for_alone_is_the_marker_and_its_tag() -> None:
    selection = tier2_selection(MARKER, [], only="acp")

    assert selection.expression == "local_stack and runtime_acp"
    assert selection.only == "acp"


def test_the_base_group_alone_leaves_out_every_known_runtime() -> None:
    selection = tier2_selection(MARKER, [], only="base")

    tags = sorted(f"runtime_{name}" for name in known())
    assert selection.expression == "local_stack" + "".join(f" and not {tag}" for tag in tags)
    assert selection.only == "base"


def test_a_runtime_the_configuration_names_is_known() -> None:
    selection = tier2_selection(MARKER, ["svc_agent"], configured=["svc_agent"])

    assert selection.expression == "local_stack and not runtime_svc_agent"


def test_an_unknown_runtime_is_refused_naming_it() -> None:
    with pytest.raises(ValueError, match="nonesuch"):
        tier2_selection(MARKER, ["nonesuch"])
    with pytest.raises(ValueError, match="nonesuch"):
        tier2_selection(MARKER, [], only="nonesuch")


def test_the_name_base_cannot_be_blocked() -> None:
    with pytest.raises(ValueError, match="base"):
        tier2_selection(MARKER, ["base"])


def test_the_same_inputs_always_give_the_same_text() -> None:
    first = tier2_selection(MARKER, ["claude_code", "acp"])
    again = tier2_selection(MARKER, ["acp", "claude_code", "acp"])

    assert first == again
