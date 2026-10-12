"""The setup questions a runtime declares, and what a runtime without the hooks offers."""

from __future__ import annotations

import pytest

from agent_build_kit.runtimes import acp, claude_code
from agent_build_kit.runtimes.base import (
    ModelSource,
    Question,
    QuestionKind,
    candidates_of,
    models_of,
    name_validator,
    questions_of,
)
from tests.runtimes.probe_fakes import Host
from tests.runtimes.stand_in import StandInRuntime

RUNTIMES = (claude_code.RUNTIME, acp.RUNTIME)


def _argv_questions(runtime: object) -> list[Question]:
    return [q for q in runtime.setup_questions() if q.kind == QuestionKind.ARGV]  # type: ignore[attr-defined]


@pytest.mark.parametrize("runtime", RUNTIMES, ids=lambda r: r.name)
def test_every_question_carries_a_prompt_a_default_a_validator_and_its_key(runtime) -> None:
    questions = runtime.setup_questions()

    assert questions
    for question in questions:
        assert question.prompt.strip()
        assert isinstance(question.default, str)
        assert callable(question.validator)
        assert question.key
        assert question.writes_to


@pytest.mark.parametrize("runtime", RUNTIMES, ids=lambda r: r.name)
def test_a_command_answer_is_accepted_on_the_path_and_refused_otherwise(runtime) -> None:
    host = Host(("on-path",))
    [question, *_] = _argv_questions(runtime)

    assert question.validator("on-path --flag", host.which) is None
    assert question.validator("off-path --flag", host.which)
    assert question.validator("", host.which)
    assert question.validator("   ", host.which)


def test_a_name_answer_is_accepted_only_when_known() -> None:
    validate = name_validator(("alpha", "beta"))

    assert validate("alpha", Host().which) is None
    assert validate("gamma", Host().which)


def test_a_runtime_registered_with_its_own_questions_is_returned_as_declared() -> None:
    declared = [
        Question(
            key="region",
            prompt="Which region?",
            default="north",
            kind=QuestionKind.TEXT,
            validator=lambda answer, which: None,
            writes_to="runtimes.stand_in.region",
        )
    ]

    class Asking(StandInRuntime):
        def setup_questions(self) -> list[Question]:
            return declared

    assert questions_of(Asking()) == declared


def test_a_runtime_without_the_hooks_offers_no_candidates_questions_or_list() -> None:
    runtime = StandInRuntime()
    host = Host()

    assert candidates_of(runtime, host.which, host.run) == []
    assert questions_of(runtime) == []
    listed = models_of(runtime)
    assert listed.models == ()
    assert listed.source == ModelSource.NONE
    assert listed.note
