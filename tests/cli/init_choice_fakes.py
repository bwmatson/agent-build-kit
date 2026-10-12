"""What `abk init`'s runtime question is asked about: runtimes that offer a candidate
for a program on a faked path, answer their own setup questions, and run research and
propose through the shared fake model — and the person answering at the terminal."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import init as init_cmd
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.base import (
    Candidate,
    Question,
    QuestionKind,
    Run,
    Which,
    validate_argv,
)
from tests.cli.test_init import fake_claude
from tests.runtimes.probe_fakes import Host, table
from tests.runtimes.selectable import SelectableRuntime


class Offering(SelectableRuntime):
    """A protocol-style runtime: one candidate, usable when its program is on the path."""

    def __init__(
        self,
        name: str,
        *,
        events: list[str],
        questions: Sequence[Question] = (),
    ) -> None:
        super().__init__(name, requires=("command",), log=events)
        self.program = f"{name}-bin"
        self.questions = list(questions)
        self.requests: list[AgentRequest] = []

    @property
    def label(self) -> str:
        return f"{self.name} agent"

    @property
    def command_prompt(self) -> str:
        return f"{self.name} start command"

    def detect(self, which: Which, run: Run) -> list[Candidate]:
        found = which(self.program) is not None
        return [
            Candidate(
                runtime=self.name,
                command=(self.program, "acp"),
                label=self.label,
                usable=found,
                reasons=() if found else (f"{self.program} is not on the path",),
                verified="documented only",
            )
        ]

    def setup_questions(self) -> list[Question]:
        return [
            Question(
                key="command",
                prompt=self.command_prompt,
                default=f"{self.program} acp",
                kind=QuestionKind.ARGV,
                validator=validate_argv,
                writes_to=f"runtimes.{self.name}.command",
            ),
            *self.questions,
        ]

    def run(self, request: AgentRequest) -> AgentResult:
        self.log.append("run")
        self.requests.append(request)
        text = fake_claude(["claude", "-p", request.prompt], cwd=request.cwd)
        return AgentResult(ok=True, text=text)


class Answers:
    """The person at the terminal: `script` in order, then a keyword's answer for the
    prompt it appears in, then Enter. Every prompt is kept, in the order asked."""

    def __init__(
        self,
        *script: str,
        by_keyword: dict[str, str] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.script = list(script)
        self.by_keyword = by_keyword or {}
        self.events = events if events is not None else []
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.events.append("ask")
        self.prompts.append(prompt)
        for keyword, answer in self.by_keyword.items():
            if keyword in prompt.lower():
                return answer
        return self.script.pop(0) if self.script else ""


def machine(
    monkeypatch: pytest.MonkeyPatch,
    programs: tuple[str, ...],
    *offered: SelectableRuntime,
    events: list[str],
) -> None:
    """A machine with `programs` on its path and only `offered` registered: the known-agent
    table empty, and every look at the path noted in `events` as "probe"."""
    host = Host(programs)

    def which(program: str) -> str | None:
        events.append("probe")
        return host.which(program)

    monkeypatch.setattr(init_cmd, "which", which)
    monkeypatch.setattr(init_cmd, "probe_run", host.run)
    monkeypatch.setattr(runtimes, "_REGISTRY", {r.name: r for r in offered})
    table(monkeypatch)


def answering(monkeypatch: pytest.MonkeyPatch, answers: Answers) -> Answers:
    monkeypatch.setattr(init_cmd, "ask", answers)
    return answers


def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Research and propose may only reach a runtime they are handed."""

    def refuse(*args: object, **kwargs: object) -> str:
        pytest.fail("the default model was used")

    monkeypatch.setattr(init_cmd, "run_claude", refuse)
