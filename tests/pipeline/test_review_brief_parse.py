"""A review reply's focus list and skippable list (spec: reviewers-are-told-where-to-look)."""

import json
import re

import pytest

from agent_build_kit.pipeline.stack_runner import parse_verdict
from agent_build_kit.pipeline.unit_store import FocusEntry, FocusKind, SkipEntry
from agent_build_kit.pipeline.wiring import REVIEW_BRIEF_PROMPT

CHANGES = ["The marker registry exists."]


def reply(description: object = None, **fields: object) -> str:
    payload: dict = {"approved": True, "feedback": "", **fields}
    if description is not None:
        payload["description"] = description
    return json.dumps(payload)


def described(**lists: object) -> str:
    return reply({"summary": "Registers markers.", "changes": CHANGES, **lists})


def focus(place: str, reason: str) -> dict:
    return {"place": place, "reason": reason}


def test_focus_and_skippable_entries_are_read_with_place_and_reason_in_order() -> None:
    verdict = parse_verdict(
        described(
            focus=[focus("src/b.py", "the payload shape"), focus("src/a.py", "a new default")],
            skippable=[{"place": "src/old.py", "reason": "moved with no change"}],
        )
    )

    assert verdict.description is not None
    assert [(e.place, e.reason) for e in verdict.description.focus] == [
        ("src/b.py", "the payload shape"),
        ("src/a.py", "a new default"),
    ]
    assert verdict.description.skippable == (
        SkipEntry(place="src/old.py", reason="moved with no change"),
    )


@pytest.mark.parametrize("kind", list(FocusKind))
def test_a_reason_naming_one_of_the_four_kinds_is_kept_with_that_kind(kind: FocusKind) -> None:
    verdict = parse_verdict(described(focus=[focus("src/a.py", kind.value)]))

    assert verdict.description is not None
    assert verdict.description.focus == (
        FocusEntry(place="src/a.py", reason=kind.value, kind=kind),
    )


def test_any_other_reason_is_kept_as_written_with_no_kind() -> None:
    verdict = parse_verdict(described(focus=[focus("src/a.py", "looks risky to me")]))

    assert verdict.description is not None
    assert verdict.description.focus == (
        FocusEntry(place="src/a.py", reason="looks risky to me", kind=None),
    )


def test_more_than_five_entries_in_either_list_keeps_the_first_five() -> None:
    verdict = parse_verdict(
        described(
            focus=[focus(f"src/f{n}.py", "r") for n in range(8)],
            skippable=[{"place": f"src/s{n}.py", "reason": "r"} for n in range(8)],
        )
    )

    assert verdict.description is not None
    assert [e.place for e in verdict.description.focus] == [f"src/f{n}.py" for n in range(5)]
    assert [e.place for e in verdict.description.skippable] == [f"src/s{n}.py" for n in range(5)]


def test_entries_with_a_blank_place_or_a_blank_skip_reason_are_dropped() -> None:
    verdict = parse_verdict(
        described(
            focus=[focus("  ", "r"), focus("src/a.py", "r")],
            skippable=[
                {"place": "", "reason": "r"},
                {"place": "src/s.py", "reason": "  "},
                {"place": "src/t.py", "reason": "r"},
            ],
        )
    )

    assert verdict.description is not None
    assert [e.place for e in verdict.description.focus] == ["src/a.py"]
    assert [e.place for e in verdict.description.skippable] == ["src/t.py"]


def test_an_over_long_entry_is_cut() -> None:
    long = "x" * 5000

    verdict = parse_verdict(
        described(
            focus=[focus("src/a.py", long)], skippable=[{"place": "src/b.py", "reason": long}]
        )
    )

    assert verdict.description is not None
    assert 0 < len(verdict.description.focus[0].reason) < 1000
    assert 0 < len(verdict.description.skippable[0].reason) < 1000


def test_a_place_in_both_lists_stays_in_the_focus_list_only() -> None:
    verdict = parse_verdict(
        described(
            focus=[focus("src/a.py", "r")],
            skippable=[
                {"place": "src/a.py", "reason": "r"},
                {"place": "src/b.py", "reason": "r"},
            ],
        )
    )

    assert verdict.description is not None
    assert [e.place for e in verdict.description.focus] == ["src/a.py"]
    assert [e.place for e in verdict.description.skippable] == ["src/b.py"]


@pytest.mark.parametrize("malformed", ["a sentence", {"place": "src/a.py"}, 7, [3, None, "x"]])
def test_a_list_that_is_not_a_list_of_entries_reads_as_empty(malformed: object) -> None:
    verdict = parse_verdict(described(focus=[focus("src/ok.py", "r")], skippable=malformed))

    assert verdict.description is not None
    assert [e.place for e in verdict.description.focus] == ["src/ok.py"]
    assert verdict.description.skippable == ()
    assert verdict.description.changes == tuple(CHANGES)

    verdict = parse_verdict(described(focus=malformed))
    assert verdict.description is not None
    assert verdict.description.focus == ()


def test_a_reply_that_is_not_json_still_reads_without_raising_beside_a_good_one() -> None:
    unreadable = parse_verdict("focus: src/a.py, skippable: src/b.py")
    readable = parse_verdict(described(focus=[focus("src/a.py", "r")]))

    assert unreadable.approved is False
    assert unreadable.description is None
    assert readable.description is not None
    assert len(readable.description.focus) == 1


def test_the_lists_do_not_change_how_the_other_fields_are_read() -> None:
    verdict = parse_verdict(
        reply(
            {
                "summary": "Registers markers.",
                "changes": CHANGES,
                "focus": [focus("src/a.py", "r")],
                "skippable": "nope",
            },
            findings=[],
            needs_human=True,
            feedback="see this",
        )
    )

    assert (verdict.approved, verdict.needs_human, verdict.feedback) == (True, True, "see this")
    assert verdict.findings == ()
    assert verdict.description is not None
    assert [e.place for e in verdict.description.focus] == ["src/a.py"]


def prompt_reasons() -> list[str]:
    """The reasons exactly as the brief prompt spells them, from its sentence naming them."""
    sentence = (
        " ".join(REVIEW_BRIEF_PROMPT.split()).split("which is one of ", 1)[1].split("(", 1)[0]
    )
    return re.findall(r"`([^`]+)`", sentence)


def kind_of(reason: str) -> FocusKind | None:
    description = parse_verdict(described(focus=[focus("src/a.py", reason)])).description
    assert description is not None
    return description.focus[0].kind


def test_the_prompt_names_each_reason_kind() -> None:
    assert len(prompt_reasons()) == len(FocusKind)


@pytest.mark.parametrize("index", range(len(FocusKind)))
def test_each_reason_as_the_prompt_spells_it_comes_back_with_its_kind(index: int) -> None:
    assert kind_of(prompt_reasons()[index]) == list(FocusKind)[index]


def test_a_reason_is_matched_ignoring_case() -> None:
    assert kind_of("Behaviour Change") == FocusKind.BEHAVIOUR_CHANGE
