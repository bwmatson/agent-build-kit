"""The planning-in-repo acceptance file drives a protocol stand-in and carries no runtime tag.

Its agent is the scripted one over stdio, which bills nothing and needs no model backend, so a
held `acp` split must not park it (spec: planning-in-the-working-copy, task 17.7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.runtime_tags import runtime_tags

MODULE = Path(__file__).parent / "integration" / "test_planning_in_repo_live_stack.py"
UNTAGGED = "local_stack and not runtime_acp and not runtime_claude_code"


def test_the_file_is_selected_whole_by_the_expression_that_leaves_out_both_runtimes(
    pytester: pytest.Pytester,
) -> None:
    everything, _ = pytester.inline_genitems(str(MODULE))
    untagged, _ = pytester.inline_genitems("-m", UNTAGGED, str(MODULE))

    assert everything
    assert [i.nodeid for i in untagged] == [i.nodeid for i in everything]
    assert all(runtime_tags(i) == [] for i in untagged)
    assert all(i.get_closest_marker("local_stack") is not None for i in untagged)
