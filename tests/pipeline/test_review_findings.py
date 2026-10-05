"""What a review round looks for, and the findings it hands back.

The reviewer is faked at its boundary: the raw JSON reply the review run
returns, which the loop parses. Findings come back as a list, are rendered to
the builder's feedback, recorded on the round with ids and the commit judged,
and every earlier required finding is answered by id in a later round.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline import stack_runner
from agent_build_kit.pipeline.stack_runner import (
    Finding,
    RunOutcome,
    _earlier_rounds,
    parse_verdict,
    render_findings,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.graph_driver import run_on_graph
from tests.pipeline.test_stack_runner import Recorder, make_runner


def _flat(text: str) -> str:
    return " ".join(text.split())


def _finding(**fields: object) -> dict:
    return {
        "file": "src/pkg/units.py",
        "line": 182,
        "summary": "waiting_on does not look through a satisfied dependency",
        "consequence": "with c/1 planned and c/2 satisfied on it, c/3 builds without c/1",
        "done": "iterate through_satisfied() as base_of does",
        "required": True,
        **fields,
    }


def _reply(*findings: dict, approved: bool = False, **fields: object) -> str:
    return json.dumps({"approved": approved, "findings": list(findings), "feedback": "", **fields})


_FIXED_1_1 = {"id": "1.1", "status": "fixed"}


class Watching(Recorder):
    """Snapshots what the unit stores while a round exists: `run` clears the
    rounds once the unit is in review, so the store cannot be read after."""

    store: UnitStore

    def __init__(self) -> None:
        super().__init__()
        self.rounds_at_review: list[list[dict]] = []
        self.heads_at_review: list[str] = []
        self.rework_rounds: list[list[dict]] = []
        self.rework_feedback: list[str] = []

    def review(self, *, cwd: Path, context: str = "", **session: Any) -> str:
        self.rounds_at_review.append(list(self.store.get(unit().id).review_rounds))
        self.heads_at_review.append(self.head(cwd))
        return super().review(cwd=cwd, context=context, **session)

    def claude(self, prompt: str, *, cwd: Path, **session: Any) -> str:
        if "review of this branch" in prompt:
            stored = self.store.get(unit().id)
            self.rework_rounds.append(list(stored.review_rounds))
            self.rework_feedback.append(stored.feedback)
        return super().claude(prompt, cwd=cwd, **session)


def _run(tmp_path: Path, verdicts: list[str]) -> tuple[Watching, UnitStore, RunOutcome]:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Watching()
    recorder.store = store
    recorder.verdicts = list(verdicts)
    outcome = run_on_graph(make_runner(store, recorder, tmp_path), unit())
    return recorder, store, outcome


def _rework_prompts(recorder: Recorder) -> list[str]:
    return [p for p in recorder.prompts if "review of this branch" in p]


# 1.1 — the verdict carries a list


def test_a_findings_list_is_parsed_into_findings() -> None:
    optional = _finding(required=False, line=None, file="docs/a.md", summary="wording")
    verdict = parse_verdict(_reply(_finding(), optional))

    first, second = verdict.findings
    assert isinstance(first, Finding)
    assert (first.file, first.line) == ("src/pkg/units.py", 182)
    assert first.summary.startswith("waiting_on does not look")
    assert first.consequence.startswith("with c/1 planned")
    assert first.done == "iterate through_satisfied() as base_of does"
    assert first.required is True
    assert (second.file, second.line, second.required) == ("docs/a.md", None, False)


def test_a_prose_only_verdict_parses_as_before() -> None:
    verdict = parse_verdict('{"approved": false, "feedback": "use a Sequence"}')

    assert verdict.findings == ()
    assert verdict.feedback == "use a Sequence"
    assert verdict.approved is False


# 1.2 — approval and required findings


def test_approving_while_listing_a_required_finding_is_not_an_approval(tmp_path: Path) -> None:
    recorder, _, _ = _run(
        tmp_path,
        [_reply(_finding(), approved=True), _reply(approved=True, earlier=[_FIXED_1_1])],
    )

    assert recorder.events.count("review") == 2, "the first verdict did not approve"
    assert "claude:rework" in recorder.events
    assert "waiting_on does not look" in _rework_prompts(recorder)[0]


@pytest.mark.parametrize(
    "answer", [{"earlier": [{"id": "1.1", "status": "open"}]}, {}], ids=["open", "unanswered"]
)
def test_an_earlier_finding_left_open_reaches_the_builder_whole(
    tmp_path: Path, answer: dict
) -> None:
    recorder, _, _ = _run(
        tmp_path,
        [
            _reply(_finding()),
            _reply(approved=True, **answer),
            _reply(approved=True, earlier=[_FIXED_1_1]),
        ],
    )

    prompt = _rework_prompts(recorder)[1]
    assert "waiting_on does not look" in prompt
    assert "with c/1 planned and c/2 satisfied" in prompt
    assert "iterate through_satisfied()" in prompt


def test_approving_with_only_optional_findings_is_an_approval(tmp_path: Path) -> None:
    recorder, store, outcome = _run(
        tmp_path, [_reply(_finding(required=False, consequence=""), approved=True)]
    )

    assert recorder.events.count("review") == 1
    assert "claude:rework" not in recorder.events
    assert store.get(unit().id).approved
    assert outcome.status == "open"


# 1.3 — rendering


def test_rendered_findings_put_required_first_and_carry_location_consequence_and_done() -> None:
    optional = Finding(file="docs/a.md", summary="tidy the wording", required=False)
    required = Finding(**_finding(line=7, file="src/b.py", summary="lock leaks"))

    text = render_findings([optional, required])

    assert text.index("lock leaks") < text.index("tidy the wording")
    assert "src/b.py:7" in text
    assert required.consequence in text
    assert required.done in text
    assert "docs/a.md" in text


def test_the_unit_stores_and_the_rework_prompt_carries_the_rendered_findings(
    tmp_path: Path,
) -> None:
    optional = _finding(required=False, summary="tidy the wording", consequence="")
    recorder, _, _ = _run(tmp_path, [_reply(optional, _finding()), _reply(approved=True)])

    prompt = _rework_prompts(recorder)[0]
    stored_round = recorder.rework_rounds[0][0]["asked"]
    assert recorder.rework_feedback[0] == stored_round
    for text in (prompt, stored_round, recorder.rework_feedback[0]):
        assert "src/pkg/units.py:182" in text
        assert "with c/1 planned and c/2 satisfied" in text
        assert "iterate through_satisfied()" in text
        assert text.index("waiting_on does not look") < text.index("tidy the wording")


# 1.4 — a required finding with no consequence


def test_a_required_finding_without_a_consequence_still_blocks_is_marked_and_counted(
    tmp_path: Path,
) -> None:
    bare = _finding(summary="the cache is never invalidated")
    del bare["consequence"]
    recorder, _, _ = _run(
        tmp_path, [_reply(bare, approved=True), _reply(approved=True, earlier=[_FIXED_1_1])]
    )

    assert recorder.events.count("review") == 2, "not approved over the omission"
    prompt = _rework_prompts(recorder)[0]
    assert "the cache is never invalidated" in prompt
    assert "(no consequence stated)" in prompt
    assert any("no consequence" in m.lower() and "1" in m for m in recorder.logged)


# 1.5 — the optional cap


def _optionals(count: int) -> list[dict]:
    return [
        _finding(required=False, summary=f"optional-{n}", consequence="")
        for n in range(1, count + 1)
    ]


def test_optional_findings_past_five_are_cut_and_counted(tmp_path: Path) -> None:
    recorder, _, _ = _run(
        tmp_path,
        [_reply(_finding(summary="the one required"), *_optionals(8)), _reply(approved=True)],
    )

    prompt = _rework_prompts(recorder)[0]
    assert "the one required" in prompt
    for n in range(1, 6):
        assert f"optional-{n}" in prompt
    for n in range(6, 9):
        assert f"optional-{n}" not in prompt
    assert any("3" in m and "left out" in m.lower() for m in recorder.logged)


def test_required_findings_are_never_cut(tmp_path: Path) -> None:
    required = [_finding(summary=f"required-{n}") for n in range(1, 8)]
    recorder, _, _ = _run(tmp_path, [_reply(*required, *_optionals(8)), _reply(approved=True)])

    prompt = _rework_prompts(recorder)[0]
    for n in range(1, 8):
        assert f"required-{n}" in prompt


# 1.6 — the record of a round


def test_a_round_keeps_its_findings_with_ids_and_the_commit_judged(tmp_path: Path) -> None:
    second = _finding(summary="second problem", file="src/b.py", line=None)
    recorder, _, _ = _run(tmp_path, [_reply(_finding(), second), _reply(approved=True)])

    recorded = recorder.rounds_at_review[1][0]
    assert [f["id"] for f in recorded["findings"]] == ["1.1", "1.2"]
    assert recorded["findings"][1]["summary"] == "second problem"
    assert recorded["judged"] == recorder.heads_at_review[0], "the head the reviewer was given"


def test_rounds_recorded_before_findings_still_load_and_render_as_prose(tmp_path: Path) -> None:
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.upsert([unit()])
    store.set_review_rounds(
        unit().id,
        (
            {"asked": "Use a Sequence, list is invariant", "response": "Done, switched."},
            {
                "asked": "rendered",
                "response": "Fixed.",
                "judged": "sha-9",
                "findings": [{**_finding(), "id": "2.1"}],
            },
        ),
    )

    note = _earlier_rounds(UnitStore(path).get(unit().id).review_rounds)

    assert "Use a Sequence, list is invariant" in note
    assert "Done, switched." in note
    assert "2.1" in note, "the later round is listed by id"


# 1.7 — the next round's note


def test_the_note_names_the_judged_commit_and_lists_each_required_finding_whole() -> None:
    rounds = (
        {
            "asked": "rendered",
            "response": "I moved the check into base_of.",
            "judged": "sha-abc",
            "findings": [
                {**_finding(), "id": "1.1"},
                {**_finding(summary="optional aside", required=False), "id": "1.2"},
            ],
        },
    )

    note = _earlier_rounds(rounds)

    assert "sha-abc..HEAD" in note.replace(" ", "")
    for part in ("1.1", "src/pkg/units.py", "waiting_on does not look", "c/3 builds without c/1"):
        assert part in note
    assert "I moved the check into base_of." in note
    assert "optional aside" not in note, "only required findings are carried forward"


def test_a_note_too_long_leaves_out_whole_findings_fixed_ones_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stack_runner, "ROUND_CHARS", 1400)
    statuses = ["fixed", "fixed", "fixed", "open", "open", "open"]
    findings = [
        {
            **_finding(summary=f"S{n}", consequence=f"C{n} " + "x" * 150),
            "id": f"1.{n}",
            "status": status,
        }
        for n, status in enumerate(statuses, start=1)
    ]
    rounds = ({"asked": "r", "response": "did it", "judged": "sha-abc", "findings": findings},)

    note = _earlier_rounds(rounds)

    shown = [n for n in range(1, 7) if f"C{n} " + "x" * 150 in note]
    for n in range(1, 7):
        assert (f"C{n} " in note) == (n in shown), f"finding 1.{n} is whole or absent"
    assert {4, 5, 6} <= set(shown), "open findings are kept"
    left_out = 6 - len(shown)
    assert left_out >= 1
    assert re.search(rf"\b{left_out}\b[^\n]*(left out|omitted)", note)


# 1.8 — answering earlier findings


@pytest.mark.parametrize(
    ("answers", "approves"),
    [
        ([{"id": "1.1", "status": "fixed"}], True),
        ([{"id": "1.1", "status": "declined"}], True),
        ([{"id": "1.1", "status": "open"}], False),
        ([], False),
    ],
)
def test_a_later_round_approves_only_when_every_earlier_finding_is_answered(
    tmp_path: Path, answers: list[dict], approves: bool
) -> None:
    recorder, _, _ = _run(
        tmp_path,
        [_reply(_finding()), _reply(approved=True, earlier=answers), _reply(approved=True)],
    )

    assert (recorder.events.count("review") == 2) is approves


def test_every_earlier_finding_must_be_answered_not_only_one(tmp_path: Path) -> None:
    second = _finding(summary="second problem")
    recorder, _, _ = _run(
        tmp_path,
        [
            _reply(_finding(), second),
            _reply(approved=True, earlier=[{"id": "1.1", "status": "fixed"}]),
            _reply(
                approved=True,
                earlier=[{"id": "1.1", "status": "fixed"}, {"id": "1.2", "status": "fixed"}],
            ),
        ],
    )

    assert recorder.events.count("review") == 3, "1.2 was left unanswered on round two"


def test_the_later_rounds_context_lists_the_earlier_finding_and_judged_commit(
    tmp_path: Path,
) -> None:
    recorder, _, _ = _run(
        tmp_path,
        [_reply(_finding()), _reply(approved=True, earlier=[{"id": "1.1", "status": "fixed"}])],
    )

    context = recorder.contexts[1]
    assert "1.1" in context
    assert "c/3 builds without c/1" in context
    assert recorder.heads_at_review[0] in context, "the commit round one judged"


# 1.9 — the method, and the tools


def test_the_review_prompt_names_its_angles_and_the_reviewer_stays_read_only() -> None:
    from agent_build_kit.pipeline.wiring import REVIEW_PROMPT, REVIEW_TOOLS

    review = _flat(REVIEW_PROMPT).lower()
    assert "enclosing function" in review
    assert "removed" in review and "enforced" in review
    assert "callers" in review and "callees" in review
    assert "re-read" in review or "re-check" in review
    assert '"findings"' in review and "consequence" in review
    assert "cannot name" in review and "required: false" in review
    assert "most important first" in review and "first five" in review
    assert "the rule and where it is written" in review

    tools = set(re.findall(r"\w+(?:\([^)]*\))?", REVIEW_TOOLS))
    assert tools == {
        "Read",
        "Grep",
        "Glob",
        "Bash(git diff*)",
        "Bash(git log*)",
        "Bash(git show*)",
    }


# review-round fixes


def _stored_round(**fields: object) -> dict:
    return {
        "asked": "rendered",
        "response": "done",
        "judged": "sha-1",
        "findings": [{**_finding(), "id": "1.1", "status": "", **fields}],
    }


def _store_with(tmp_path: Path, *rounds: dict) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_review_rounds(unit().id, rounds)
    return store


def _resumed_run(store: UnitStore, verdicts: list[str]) -> Watching:
    recorder = Watching()
    recorder.store = store
    recorder.verdicts = list(verdicts)
    store.set_feedback(unit().id, "fix it")
    run_on_graph(make_runner(store, recorder, store.path.parent), unit())
    return recorder


def test_a_reply_without_an_earlier_key_does_not_approve_over_an_open_finding(
    tmp_path: Path,
) -> None:
    recorder, _, _ = _run(
        tmp_path,
        [_reply(_finding()), '{"approved": true, "feedback": ""}', _reply(approved=True)],
    )

    assert recorder.events.count("review") == 3


def test_prose_only_earlier_rounds_and_a_prose_only_approval_still_approve(
    tmp_path: Path,
) -> None:
    recorder, _, _ = _run(
        tmp_path,
        [json.dumps({"approved": False, "feedback": "use a Sequence"}), _reply(approved=True)],
    )

    assert recorder.events.count("review") == 2
    assert "claude:rework" in recorder.events


def test_a_rework_with_a_stored_round_numbers_its_findings_after_it(tmp_path: Path) -> None:
    store = _store_with(tmp_path, _stored_round())
    recorder = _resumed_run(store, [_reply(_finding(summary="new"), approved=False)] * 3)

    ids = [f["id"] for r in recorder.rework_rounds[0] for f in r["findings"]]
    assert ids == ["1.1", "2.1"]


def test_a_note_never_leaves_out_an_unresolved_finding() -> None:
    findings = [
        {**_finding(summary=f"S{n}", consequence="x" * 590), "id": f"1.{n}", "status": ""}
        for n in range(1, 11)
    ]
    note = _earlier_rounds(
        ({"asked": "r", "response": "", "judged": "sha-1", "findings": findings},)
    )

    for n in range(1, 11):
        assert f"[1.{n}]" in note
    assert note.count("x" * 590) == 10
    assert "left out" not in note


def test_an_open_answer_to_a_finding_recorded_fixed_is_not_an_approval() -> None:
    entries = ({"findings": _stored_round(status="fixed")["findings"]},)
    answers = stack_runner._parse_answers([{"id": "1.1", "status": "open"}])

    assert stack_runner._unresolved(entries, answers) == ["1.1"]


@pytest.mark.parametrize(
    "raw",
    [
        {"id": "1.1", "status": "declined", "reason": "holds"},
        {"id": 1.1, "status": "declined"},
        {"id": "1.1", "status": "Declined "},
    ],
)
def test_a_plausibly_shaped_answer_is_read(raw: dict) -> None:
    answers = stack_runner._parse_answers([raw])

    assert answers is not None
    assert [(a.id, a.status) for a in answers] == [("1.1", "declined")]


def test_an_unknown_status_counts_as_open() -> None:
    answers = stack_runner._parse_answers([{"id": "1.1", "status": "maybe"}])

    assert stack_runner._unresolved(({"findings": _stored_round()["findings"]},), answers) == [
        "1.1"
    ]


@pytest.mark.parametrize("item", ["not a dict", {"summary": "no file"}])
def test_an_unreadable_finding_blocks_approval(item: object) -> None:
    verdict = parse_verdict(json.dumps({"approved": True, "findings": [item]}))

    (finding,) = verdict.findings
    assert (finding.file, finding.required) == ("(unreadable)", True)


def test_an_optional_finding_with_an_extra_key_or_a_line_range_stays_readable() -> None:
    verdict = parse_verdict(
        _reply(_finding(required=False, severity="low", line="12-15", consequence=""))
    )

    (finding,) = verdict.findings
    assert (finding.required, finding.line, finding.file) == (False, None, "src/pkg/units.py")


def test_optional_findings_on_an_approval_are_recorded_with_the_deferred_points(
    tmp_path: Path,
) -> None:
    optional = _finding(required=False, summary="tidy the wording", consequence="")
    _run(tmp_path, [_reply(optional, approved=True)])

    recorded = (
        tmp_path / "meta" / "openspec" / "changes" / "add-marker" / "follow-ups.md"
    ).read_text()
    assert "src/pkg/units.py:182 — tidy the wording" in recorded
