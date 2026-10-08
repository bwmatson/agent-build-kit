"""The agent callables the session tests drive a runner with: a `run` that takes
the model per call, and a reviewer, both reporting a numbered session the way a
runtime does (the id as it starts, and the result as it ends)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from agent_build_kit import config as config_module
from agent_build_kit.config import ModelsConfig
from agent_build_kit.runtimes import AgentResult
from tests.runner_fakes import Killed, Recorder

MODELS = ModelsConfig(
    implement="m-implement", rework="m-rework", review="m-review", rework_review="m-rereview"
)


def distinct_models() -> None:
    """Each model role named differently; the suite's autouse fixture puts the config back."""
    current = config_module.active()
    config_module.activate(
        current.model_copy(update={"models": MODELS}), config_module.active_root()
    )


class Call(NamedTuple):
    prompt: str
    cwd: Path
    model: str
    resume_session: str


class Runs:
    """A `run`: records each call, answers as the recorder's builder does."""

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self.calls: list[Call] = []

    def __call__(
        self,
        prompt: str,
        *,
        cwd: Path,
        model: str,
        resume_session: str = "",
        on_session: Callable[[str], None] | None = None,
        on_result: Callable[..., None] | None = None,
        **more: Any,
    ) -> str:
        self.calls.append(Call(prompt, cwd, model, resume_session))
        session = f"sess-{len(self.calls)}"
        if on_session:
            on_session(session)
        answer = self.recorder.claude(prompt, cwd=cwd)
        if on_result:
            result = AgentResult(ok=True, text=answer, session_id=session)
            on_result(result, role="implement", model=model, runtime="fake")
        return answer


class Reviews:
    """A reviewer for both review entry points; dies, as a power loss does, on call `kill_on`."""

    def __init__(self, recorder: Recorder, *, kill_on: int = 0) -> None:
        self.recorder = recorder
        self.kill_on = kill_on
        self.count = 0

    def __call__(
        self,
        *,
        cwd: Path,
        context: str = "",
        resume_session: str = "",
        on_session: Callable[[str], None] | None = None,
        on_result: Callable[..., None] | None = None,
    ) -> str:
        self.count += 1
        if self.count == self.kill_on:
            raise Killed("power loss")
        session = f"rev-{self.count}"
        if on_session:
            on_session(session)
        answer = self.recorder.review(cwd=cwd, context=context)
        if on_result:
            result = AgentResult(ok=True, text=answer, session_id=session)
            on_result(result, role="review", model="m-review", runtime="fake")
        return answer
