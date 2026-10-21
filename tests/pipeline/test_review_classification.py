"""The reviewer's reply carries a classification and drivers (spec: review-classification)."""

import json

import pytest

from agent_build_kit.pipeline.stack_runner import parse_verdict


def reply(**fields: object) -> str:
    return json.dumps({"approved": True, "feedback": "", **fields})


def test_a_classification_and_its_drivers_are_kept() -> None:
    verdict = parse_verdict(reply(classification="light", drivers=["src/app/marker.py", "group 2"]))

    assert verdict.classification == "light"
    assert verdict.drivers == ("src/app/marker.py", "group 2")


@pytest.mark.parametrize("tier", ["auto", "light", "full"])
def test_each_of_the_three_tiers_is_read_as_given(tier: str) -> None:
    assert parse_verdict(reply(classification=tier)).classification == tier


def test_a_classification_without_drivers_has_none() -> None:
    verdict = parse_verdict(reply(classification="auto"))

    assert verdict.classification == "auto"
    assert verdict.drivers == ()


@pytest.mark.parametrize("given", ["", "medium", "ful", None, 3, ["light"]])
def test_a_missing_or_unknown_classification_is_full_and_the_rest_is_read_as_before(
    given: object,
) -> None:
    fields = {} if given is None else {"classification": given}
    verdict = parse_verdict(
        reply(
            **fields,
            feedback="fix it",
            needs_human=True,
            escalate="class",
            findings=[{"file": "a.py", "summary": "s", "consequence": "c", "required": True}],
        )
    )

    assert verdict.classification == "full"
    assert verdict.approved is True
    assert verdict.feedback == "fix it"
    assert verdict.needs_human is True
    assert verdict.escalate is not None
    assert [f.file for f in verdict.findings] == ["a.py"]


@pytest.mark.parametrize("output", ["", "no verdict here", '{"classification": "light", '])
def test_output_that_is_not_json_is_full_and_never_raises(output: str) -> None:
    verdict = parse_verdict(output)

    assert verdict.classification == "full"
    assert verdict.approved is False
    assert "not readable" in verdict.feedback


@pytest.mark.parametrize("drivers", ["one file", 7, {"a": 1}, [1, None]])
def test_drivers_that_are_not_a_list_of_text_never_raise(drivers: object) -> None:
    verdict = parse_verdict(reply(classification="light", drivers=drivers))

    assert verdict.classification == "light"
    assert all(isinstance(driver, str) for driver in verdict.drivers)
