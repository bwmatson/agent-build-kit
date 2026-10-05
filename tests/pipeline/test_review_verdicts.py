"""How a unit's review loop ends.

A verdict used to say "approved" or "not yet", and running out of rounds threw
the unit's work away. These tests hand the loop each verdict shape a reviewer
can now give — approve with follow-ups, escalate an open-ended class, escalate
a repeated disagreement — and check what becomes of a unit whose rounds run
out: its branch pushed, its open points on the PR, the unit held for a person.

The reviewer is faked at its boundary: the raw JSON reply the review run
returns, which the loop parses.
"""

import json
from pathlib import Path

import pytest

FOLLOW_UPS = Path("openspec") / "changes" / "add-marker" / "follow-ups.md"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _verdict(**fields: object) -> str:
    return json.dumps({"approved": False, "feedback": "", **fields})


def _capturing_prs(runner, bodies: list[str]):
    def open_pr(unit, *, body: str, base: str, cwd: Path, **stacked: str) -> int:
        bodies.append(body)
        return runner.open_pr(unit, body=body, base=base, cwd=cwd, **stacked)

    return runner.model_copy(update={"open_pr": open_pr})


# 1.1 — the round note


# 1.2 — approve with follow-ups


def test_the_reviewer_is_told_what_it_may_defer_and_when_to_escalate() -> None:
    from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

    review = _flat(REVIEW_PROMPT)
    for field in ('"follow_ups"', '"escalate"', '"reasoning"'):
        assert field in review, f"the reply format carries {field}"
    for kind in ("correctness", "test_passes_regardless", "missing_test", "policy"):
        assert kind in review, f"{kind} is named as never deferrable"
    assert '"class"' in review
    assert '"disagreement"' in review


# 1.3 — what may not be deferred


# 1.4 — escalations


# 1.5 — spent rounds


def _approval_with(*items: dict) -> str:
    return json.dumps({"approved": True, "feedback": "", "follow_ups": list(items)})


@pytest.mark.parametrize(
    ("value", "kinds", "points"),
    [
        (True, ["unreadable"], ["true"]),
        (3, ["unreadable"], ["3"]),
        ({"kind": "optional", "point": "x"}, ["optional"], ["x"]),
        ("fix the lock", ["unreadable"], ["fix the lock"]),
    ],
)
def test_a_follow_ups_value_that_is_not_a_list_is_read_as_one_item(
    value: object, kinds: list[str], points: list[str]
) -> None:
    from agent_build_kit.pipeline.stack_runner import parse_verdict

    verdict = parse_verdict(json.dumps({"approved": True, "follow_ups": value}))

    assert [f.kind for f in verdict.follow_ups] == kinds
    assert [f.point for f in verdict.follow_ups] == points
