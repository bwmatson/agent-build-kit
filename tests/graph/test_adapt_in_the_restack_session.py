"""The port is the last step of the restack's order, a call of the session the first two steps
ran in, told which of them were tried and what their checks said (spec: restack-adapt).

`restack_onto` is faked at its edge: given a `resolver` it asks it twice, as the move does for
the first two steps, and then reports the conflict they could not settle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import Restacked
from tests.graph.agent_fakes import distinct_models
from tests.graph.test_build_path import build, restacked
from tests.graph.test_session_continuation import (
    CHANGE_PATH,
    OLD_REF,
    Sessions,
    agents,
)
from tests.graph_driver import fresh

HUNKS = "ORDER: hunks first, then dependent files, then a port. Conflicted: a.py"
DEPENDENT = "ORDER: hunks first. FAILED: b.py lost make_thing"
CONTINUE = "Your resolution lost make_thing; you may now change the files that depend on a.py."
TRIED = "hunks only: b.py lost make_thing; dependent files: test_marks went missing"
MISSING = "tests/test_marker.py::test_marks"


class Failing:
    """`restack_onto`: given a resolver it asks it for both steps and reports the conflict
    they could not settle; asked again, the branch is on its base."""

    def __init__(self) -> None:
        self.settled = False

    def __call__(self, **kw: Any) -> Restacked | None:
        if (resolver := kw.get("resolver")) is None or self.settled:
            return None
        self.settled = True
        resolver(HUNKS, cwd=kw["tree"])
        resolver(DEPENDENT, cwd=kw["tree"], follow_up=CONTINUE)
        return restacked(conflict="CONFLICT in a.py", old_tests=(MISSING,), tried=TRIED)


def test_a_conflict_the_first_two_steps_fail_is_ported_in_the_session_they_ran_in(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions()
    resets: list[tuple[str, str]] = []

    build(
        tmp_path,
        recorder,
        base="spec/c/2",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=Failing(),
        reset_to=lambda tree, onto, keep: resets.append((onto, keep)),
        tests_in=lambda tree: set(),
        tests_changed=lambda tree, ref: set(),
        **agents(runtime),
    )

    first, second, port, accounting = runtime.built[:4]
    assert (first.resume_session, second.resume_session) == ("", "sess-1")
    assert port.resume_session == "sess-1", "the port continues the steps' session"
    assert resets == [("spec/c/2", OLD_REF)], "the old work kept, the branch on the new base"
    assert OLD_REF in port.prompt
    assert TRIED in port.prompt, "which steps were tried and what their checks said"
    assert MISSING in accounting.prompt, "the accounting and its ask run as before"
    assert accounting.resume_session == "sess-1"


def test_a_port_whose_session_cannot_be_continued_starts_a_new_one_with_the_full_prompt(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions(refuses="the session is gone")

    outcome = build(
        tmp_path,
        recorder,
        base="spec/c/2",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=Failing(),
        reset_to=lambda tree, onto, keep: None,
        tests_in=lambda tree: {MISSING},  # carried over unchanged: nothing to account for
        tests_changed=lambda tree, ref: set(),
        **agents(runtime),
    )

    port = [r for r in runtime.built if OLD_REF in r.prompt][-1]  # after the refused attempt
    assert port.resume_session == ""
    assert CHANGE_PATH in port.prompt, "ADAPT_PROMPT in full"
    assert TRIED in port.prompt, "a new session has not seen the steps, so it is told"
    assert outcome.status != "failed", "not an error"
