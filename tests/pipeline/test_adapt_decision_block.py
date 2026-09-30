"""The adapt step's structured answer, as an agent actually writes it.

The agent finishes with prose and then one JSON block. It quotes JSON on the
way, wraps the block in a fence, sometimes leaves a field `null` and sometimes
gets cut off. Whatever it wrote, an omission or a malformed entry has to come
back as a problem naming the test, not as a block quietly accepted.
"""

from __future__ import annotations

import json

from agent_build_kit.pipeline.stack_runner import check_test_decisions, parse_test_decisions

REQUIRED = ["test_ported", "test_dropped"]
PRESENT = {"test_ported"}

COMPLETE = """I ported the unit onto the new base. Earlier I looked at {"name": "x"} in the
predecessor, which is not part of this answer.

```json
{"tests": [
  {"name": "test_ported", "decision": "adapt",
   "reason": "the predecessor renamed the marker, so the assertion reads the new one"},
  {"name": "test_dropped", "decision": "retire",
   "reason": "the predecessor removed the registry this test asserted against"}
 ],
 "summary": "ported the marker registration"}
```
"""


def _problems(answer: str) -> list[str]:
    return check_test_decisions(REQUIRED, parse_test_decisions(answer), PRESENT)


PORTED = {
    "name": "test_ported",
    "decision": "adapt",
    "reason": "the predecessor renamed the marker, so the assertion reads the new one",
}
DROPPED = {
    "name": "test_dropped",
    "decision": "retire",
    "reason": "the predecessor removed the registry this test asserted against",
}


def _answer(*entries: dict) -> str:
    return "Ported.\n\n```json\n" + json.dumps({"tests": list(entries), "summary": "s"}) + "\n```\n"


def test_a_complete_block_is_accepted() -> None:
    answer = _answer(PORTED, DROPPED)

    assert check_test_decisions(REQUIRED, parse_test_decisions(answer), PRESENT) == []


def test_a_block_that_omits_a_test_reports_it_by_name() -> None:
    problems = check_test_decisions(REQUIRED, parse_test_decisions(_answer(PORTED)), PRESENT)

    assert any("`test_dropped`" in problem for problem in problems)
    assert not any("`test_ported`" in problem for problem in problems)


def test_an_entry_without_a_decision_is_reported_by_the_test_it_names() -> None:
    answer = '{"tests": [{"name": "test_dropped", "reason": "the registry is gone"}]}'

    problems = check_test_decisions(["test_dropped"], parse_test_decisions(answer), PRESENT)

    assert len(problems) == 1
    assert "`test_dropped`" in problems[0]


def test_a_retirement_whose_reason_is_null_is_reported_as_lacking_a_reason() -> None:
    """A null is what a model writes for "nothing to say". It is a retirement
    without a reason — not "no decision", which would send the agent looking
    for a decision it did make."""
    answer = '{"tests": [{"name": "test_dropped", "decision": "retire", "reason": null}]}'

    problems = check_test_decisions(["test_dropped"], parse_test_decisions(answer), PRESENT)

    assert len(problems) == 1
    assert "`test_dropped`" in problems[0]
    assert "reason" in problems[0]
    assert "no decision" not in problems[0]


def test_a_block_that_is_cut_off_reports_every_test_it_should_have_covered() -> None:
    answer = COMPLETE[: COMPLETE.index('"reason": "the predecessor removed')]

    problems = _problems(answer)

    assert [name for name in REQUIRED if any(f"`{name}`" in p for p in problems)] == REQUIRED


def test_an_answer_with_no_block_reports_every_test_it_should_have_covered() -> None:
    problems = _problems("Ported everything; all the tests still pass.")

    assert [name for name in REQUIRED if any(f"`{name}`" in p for p in problems)] == REQUIRED


def test_an_unknown_decision_is_reported_by_name() -> None:
    answer = '{"tests": [{"name": "test_dropped", "decision": "delete", "reason": "gone"}]}'

    problems = check_test_decisions(["test_dropped"], parse_test_decisions(answer), PRESENT)

    assert len(problems) == 1
    assert "`test_dropped`" in problems[0]
    assert "delete" in problems[0]
