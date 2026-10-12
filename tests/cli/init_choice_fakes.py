"""What `abk init`'s runtime question is asked about: runtimes that offer a candidate
for a program on a faked path, answer their own setup questions, and run research and
propose through the shared fake model — and the person answering at the terminal."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import init as init_cmd
from agent_build_kit.config import runtime_entry
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.base import (
    Candidate,
    Model,
    ModelList,
    ModelSource,
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
        note: str = "",
    ) -> None:
        super().__init__(name, requires=("command",), log=events)
        self.program = f"{name}-bin"
        self.questions = list(questions)
        self.note = note
        self.requests: list[AgentRequest] = []
        self.commands: list[list[str]] = []

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
                note=self.note,
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
        self.commands.append(list(runtime_entry(name=self.name).command or []))
        text = fake_claude(["claude", "-p", request.prompt], cwd=request.cwd)
        return AgentResult(ok=True, text=text)


class Listing(Offering):
    """An offered runtime whose agent advertises models, one of them (the first unless
    `current` says) its current one."""

    def __init__(
        self, name: str, *, models: Sequence[str], events: list[str], current: int = 0
    ) -> None:
        super().__init__(name, events=events)
        self.models = tuple(models)
        self.current = current
        self.listed: list[Sequence[str] | None] = []

    def list_models(self, command: Sequence[str] | None = None) -> ModelList:
        self.listed.append(command)
        return ModelList(
            models=tuple(
                Model(name=m, current=i == self.current) for i, m in enumerate(self.models)
            ),
            source=ModelSource.ADVERTISED,
            note="the models the agent advertises when a session opens",
        )


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


# The role names a models question is asked about, a longer name before the one it contains.
ROLES = ("rework_review", "implement", "rework", "review")
MOST_PROMPTS = 80


class ModelAnswers(Answers):
    """The person answering the models questions: a prompt naming a role is answered from
    `per_role` (Enter when the role is not there), the first prompts about models that
    name none from `general` in order, and every other prompt as `Answers` does. A
    question asked over and over is a test failure, not a hang."""

    def __init__(
        self,
        *script: str,
        per_role: dict[str, str] | None = None,
        general: Sequence[str] = (),
        events: list[str] | None = None,
    ) -> None:
        super().__init__(*script, events=events)
        self.per_role = per_role or {}
        self.general = list(general)

    def __call__(self, prompt: str) -> str:
        if len(self.prompts) > MOST_PROMPTS:
            pytest.fail(f"asked {len(self.prompts)} questions; the last was {prompt!r}")
        words = prompt.lower().replace(" ", "_").replace("-", "_")
        role = next((r for r in ROLES if r in words), None)
        if role is None and not (self.general and "model" in words):
            return super().__call__(prompt)
        self.events.append("ask")
        self.prompts.append(prompt)
        return self.per_role.get(role, "") if role else self.general.pop(0)
