"""What the plan-review tests share: a planning repo with one change and planned units, a stand-in
model client that answers in the raw shape a model sends, and a tick over them.

The model is faked at the runtime seam (`StandInRuntime`), as the planner's is; the build is the
shared `Builder`, so what a tick started is `builder.started`.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import runtimes
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import shell
from agent_build_kit.pipeline.plan_review import QUESTIONS, record_path
from agent_build_kit.pipeline.units import MERGED
from agent_build_kit.runtimes import AgentRequest, AgentResult
from tests.conftest import make_installation
from tests.runtimes.stand_in import StandInRuntime
from tests.tick_pass import Builder, install_builder, isolate, stored, tick

CHANGE = "feature"
PROPOSAL = "PROPOSAL-TEXT: why the feature is wanted"
DESIGN = "DESIGN-TEXT: how the feature is built"
SPEC = "SPEC-TEXT: the feature SHALL work"
TASKS = """# Tasks

Acceptance: none — a fixture about plan review

## 1. [app] [unit-test] First group

- [ ] 1.1 Test: `tests/test_shared.py` asserts it.
- [ ] 1.2 Do it.

## 2. [app] [unit-test] Second group

- [ ] 2.1 Test: `tests/test_shared.py` asserts it again.
- [ ] 2.2 Do it.
"""
EDITED_TASKS = TASKS + "\n## 3. [app] [unit-test] Third group\n\n- [ ] 3.1 Test: it.\n"
FINDING = {
    "group": 2,
    "question": 1,
    "kind": "blocker",
    "evidence": "group 2 renames what tests/test_shared.py asserts",
}
ADVICE = {
    "group": 1,
    "question": 2,
    "kind": "advice",
    "evidence": "the Verify of 1.1 names no folder to run from",
}
FIXABLE = FINDING | {"fix": "2.1 asserts the new name"}
REPAIRED_TASKS = TASKS.replace(
    "- [ ] 2.1 Test: `tests/test_shared.py` asserts it again.",
    "- [ ] 2.1 Test: `tests/test_shared.py` asserts the new name.",
)


def needing(tasks: str, *changes: str) -> str:
    """`tasks` with a `Needs:` line on group 1 of each of `changes`, under its first group."""
    lines = "".join(f"Needs: {change} group 1\n" for change in changes)
    return tasks.replace("First group\n\n", f"First group\n\n{lines}", 1)


def neighbour_tasks(
    needs: Sequence[str], tests: Sequence[str], support: Sequence[str], repo: str = "app"
) -> str:
    """The tasks.md of a neighbouring change, headed `# Tasks` as a real one is: its one group is
    in `repo`, with a `Needs:` line on group 1 of each of `needs`, a task naming each of `tests`
    and a `Support:` line naming each of `support`."""
    body = "".join(f"Needs: {change} group 1\n" for change in needs)
    body += "".join(f"- [ ] 1.{n} Test: `{path}` asserts it.\n" for n, path in enumerate(tests, 1))
    body += "".join(f"Support: `{path}`\n" for path in support)
    return (
        f"# Tasks\n\nAcceptance: none — a neighbour in a fixture\n\n"
        f"## 1. [{repo}] [unit-test] Its group\n\n{body}"
    )


def reply(*findings: dict) -> str:
    """What a model answers: prose, then the findings as JSON."""
    return "I read the plan.\n\n" + json.dumps({"findings": list(findings)})


def question_of(request: AgentRequest) -> int:
    """The number (from 1) of the question a review pass asks, read from its prompt."""
    return next(n for n, text in enumerate(QUESTIONS, 1) if f"{n}. {text}" in request.prompt)


def change_of(request: AgentRequest) -> str:
    """The change a review pass or a repair is about, read from its prompt."""
    found = re.search(r"the change `([^`]+)`", request.prompt)
    assert found, request.prompt[:200]
    return found.group(1)


def blocker_for(request: AgentRequest) -> str:
    """An answer to a pass: one blocker, on the question the pass asks, naming the change."""
    number = question_of(request)
    return reply(
        {
            "group": 2,
            "question": number,
            "kind": "blocker",
            "evidence": f"{change_of(request)} fails question {number}",
        }
    )


class GatedRuntime(StandInRuntime):
    """A stand-in model that counts the calls in flight and keeps the most it saw.

    The first calls are held until `hold_until` calls are in flight (and the first repairs until
    `hold_repairs_until` repairs are), or `deadline` seconds pass (`repair_deadline` for the
    repairs, which a correct build never overlaps, so it may be short), so overlap shows as a
    count and nothing is timed. `refuse` may return an error for a request: that call raises it,
    and every other call in flight waits until it has, so what was in flight when it was refused
    is known.
    """

    def __init__(
        self,
        *,
        hold_until: int = 0,
        hold_repairs_until: int = 0,
        deadline: float = 5.0,
        repair_deadline: float | None = None,
        refuse: Callable[[AgentRequest], Exception | None] | None = None,
        **given: Any,
    ) -> None:
        super().__init__(**given)
        self.hold_until = hold_until
        self.hold_repairs_until = hold_repairs_until
        self.deadline = deadline
        self.repair_deadline = deadline if repair_deadline is None else repair_deadline
        self.refuse = refuse
        self.in_flight = 0
        self.most_in_flight = 0
        self.repairs_in_flight = 0
        self.most_repairs_in_flight = 0
        self.completed: list[AgentRequest] = []
        self._changed = threading.Condition()
        self._opened = {"pass": hold_until <= 0, "repair": hold_repairs_until <= 0}
        self._refused = threading.Event()

    def run(self, request: AgentRequest) -> AgentResult:
        is_repair = request.prompt.startswith("The plan of the change")
        kind = "repair" if is_repair else "pass"
        with self._changed:
            self.in_flight += 1
            self.most_in_flight = max(self.most_in_flight, self.in_flight)
            if is_repair:
                self.repairs_in_flight += 1
                self.most_repairs_in_flight = max(
                    self.most_repairs_in_flight, self.repairs_in_flight
                )
            self._changed.notify_all()
            if not self._opened[kind]:
                self._changed.wait_for(
                    lambda: (
                        self.repairs_in_flight >= self.hold_repairs_until
                        if is_repair
                        else self.in_flight >= self.hold_until
                    ),
                    timeout=self.repair_deadline if is_repair else self.deadline,
                )
                self._opened[kind] = True
                self._changed.notify_all()
        try:
            error = self.refuse(request) if self.refuse is not None else None
            if error is not None:
                self.requests.append(request)
                self._refused.set()
                raise error
            if self.refuse is not None:
                self._refused.wait(self.deadline)
            result = super().run(request)
            self.completed.append(request)
            return result
        finally:
            with self._changed:
                self.in_flight -= 1
                if is_repair:
                    self.repairs_in_flight -= 1
                self._changed.notify_all()


class Outcome(Frozen):
    """What a tick of three changes with blockers left: the most calls in flight, the calls in
    the order they started, the record file's text and the plan review log lines."""

    most_in_flight: int
    started: tuple[tuple[str, int], ...]
    record: str
    log: tuple[str, ...]


def run_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bound: int,
) -> Outcome:
    """Tick three changes (`alpha` priority 3, `zeta` 1, `mid` 2), each of whose four passes finds
    a blocker, with at most `bound` calls in flight and the first `bound` held until in flight."""
    runtime = GatedRuntime(hold_until=bound, respond=blocker_for)
    review = Review(tmp_path, monkeypatch, concurrency=bound, runtime=runtime)
    review.finish_default_change()
    for name, priority in (("alpha", 3), ("zeta", 1), ("mid", 2)):
        review.add_change(name, priority)
    capsys.readouterr()

    assert review.tick() == 0

    out = capsys.readouterr()
    lines = (re.sub(r"^\[[^\]]*\] ", "", line) for line in (out.out + out.err).splitlines())
    return Outcome(
        most_in_flight=runtime.most_in_flight,
        started=tuple((change_of(r), question_of(r)) for r in runtime.requests),
        record=record_path(review.inst).read_text(),
        log=tuple(line for line in lines if "plan review" in line),
    )


class Review:
    """A planning repo holding `feature` with two planned units, ticked with a fake model."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        review_plans: bool = True,
        concurrency: int | None = None,
        runtime: StandInRuntime | None = None,
        repos: dict[str, dict] | None = None,
    ) -> None:
        isolate(monkeypatch)
        bound = {} if concurrency is None else {"plan_review_concurrency": concurrency}
        named = {} if repos is None else {"repos": repos}
        self.inst: Installation = make_installation(
            tmp_path,
            planning={
                "state_dir": ".",
                "worktree_root": str(tmp_path.parent / "trees"),
                "review_plans": review_plans,
                **bound,
            },
            project_limits={"max_concurrent_stacks": 4, "max_units_in_progress": 50},
            **named,
        )
        self.config = self.inst.root / "abk.yaml"
        self.config.write_text(dump(self.inst.config))
        monkeypatch.chdir(self.inst.root)
        folder = self.inst.changes_dir / CHANGE
        (folder / "specs" / "feature").mkdir(parents=True)
        (folder / "proposal.md").write_text(PROPOSAL)
        (folder / "design.md").write_text(DESIGN)
        (folder / "specs" / "feature" / "spec.md").write_text(SPEC)
        self.edit_tasks(TASKS)
        self.runtime = runtime or StandInRuntime(answer=reply())
        monkeypatch.setattr(runtimes, "active", lambda: self.runtime)
        self.builder: Builder = install_builder(tmp_path, monkeypatch)
        self.builder.store.upsert([stored(f"{CHANGE}/1"), stored(f"{CHANGE}/2")])

    def add_change(self, name: str, *priorities: int) -> None:
        """Add a change `name` with the same plan as `feature` and one planned unit per priority."""
        folder = self.inst.changes_dir / name
        (folder / "specs" / "feature").mkdir(parents=True)
        (folder / "proposal.md").write_text(PROPOSAL)
        (folder / "design.md").write_text(DESIGN)
        (folder / "specs" / "feature" / "spec.md").write_text(SPEC)
        (folder / "tasks.md").write_text(TASKS)
        self.builder.store.upsert(
            [stored(f"{name}/{n}", priority=p) for n, p in enumerate(priorities, 1)]
        )

    def add_neighbour(
        self,
        name: str,
        *,
        needs: Sequence[str] = (),
        tests: Sequence[str] = (),
        support: Sequence[str] = (),
        repo: str = "app",
    ) -> None:
        """Add a change `name` with no units (so it is never reviewed itself), whose first group
        is in `repo`, has a `Needs:` line on each of `needs` and names each of `tests` in its
        tasks and each of `support` on a `Support:` line. Called again for the same name, it
        rewrites the change."""
        folder = self.inst.changes_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "proposal.md").write_text("## Why\n\nwhy\n")
        (folder / "tasks.md").write_text(neighbour_tasks(needs, tests, support, repo))

    def write_proposal(self, *, initiative: str = "", its_part: str = "") -> None:
        """Rewrite `feature`'s proposal with an `Initiative:` line and a `## Its part` section,
        each only when given. Call it before the first tick: the proposal is part of the hash."""
        lines = [PROPOSAL, ""]
        if initiative:
            lines += [f"Initiative: {initiative}", ""]
        if its_part:
            lines += ["## Its part", "", its_part, ""]
        (self.inst.changes_dir / CHANGE / "proposal.md").write_text("\n".join(lines))

    def add_outline(
        self,
        name: str,
        *,
        touches: Sequence[str],
        initiative: str = "",
        its_part: str = "",
        reworks: Sequence[str] = (),
    ) -> None:
        """Write an outline proposal under `planning.outlines`: its `Initiative:` line, its
        `## Its part`, a `Touches:` line naming each of `touches` and a `Reworks:` line per
        entry of `reworks`. Called again for the same name, it rewrites the outline."""
        folder = self.inst.root / self.inst.config.planning.outlines / name
        folder.mkdir(parents=True, exist_ok=True)
        lines = [f"# {name}", ""]
        if initiative:
            lines.append(f"Initiative: {initiative}")
        lines += [f"Touches: {', '.join(f'`{path}`' for path in touches)}"]
        lines += [f"Reworks: {rework}" for rework in reworks]
        lines += ["", "## Its part", "", its_part, ""]
        (folder / "proposal.md").write_text("\n".join(lines))

    def need(self, *changes: str, tasks: str = TASKS) -> None:
        """Make the first group of `feature`'s tasks (`tasks`, by default the fixture's) name each
        of `changes` in a `Needs:` line, and write them."""
        self.edit_tasks(needing(tasks, *changes))

    def finish_default_change(self) -> None:
        """Merge the units of `feature`, so it has nothing open and is not reviewed."""
        for number in (1, 2):
            self.builder.store.set_state(f"{CHANGE}/{number}", MERGED)

    @property
    def reviewed_order(self) -> list[str]:
        """The changes in the order their first pass was asked, read from each request."""
        order: list[str] = []
        for request in self.passes:
            if f"1. {QUESTIONS[0]}" not in request.prompt:
                continue
            order.append(change_of(request))
        return order

    def edit_tasks(self, text: str) -> None:
        (self.inst.changes_dir / CHANGE / "tasks.md").write_text(text)

    def commit_planning(self) -> None:
        """Make the planning root a git repo with everything committed, as a repair needs."""
        for args in (
            ("init", "-q", "-b", "main"),
            ("add", "."),
            ("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed"),
        ):
            shell.git(self.inst.root, *args)
        shell.git(self.inst.root, "config", "user.name", "t")
        shell.git(self.inst.root, "config", "user.email", "t@example.com")

    def repair_with(self, tasks: str, *, review_answer: str) -> None:
        """Answer a repair request with `tasks`, and every review pass with `review_answer`."""

        def respond(request: AgentRequest) -> str:
            if request.prompt.startswith("The plan of the change"):
                return f"Here it is.\n<<<TASKS\n{tasks}\nTASKS>>>\n"
            return review_answer

        self.runtime.respond = respond

    @property
    def tasks(self) -> str:
        return (self.inst.changes_dir / CHANGE / "tasks.md").read_text()

    def tick(self) -> int:
        return tick(self.inst)

    @property
    def passes(self) -> list[AgentRequest]:
        """The review passes asked, one per question per review."""
        return [r for r in self.runtime.requests if r.prompt.startswith("You are reviewing")]

    @property
    def passes_in_question_order(self) -> list[AgentRequest]:
        """The passes of the first review, each matched to its question by its prompt, not by the
        order the calls were made in."""
        return sorted(self.passes[: len(QUESTIONS)], key=question_of)

    @property
    def repairs(self) -> list[AgentRequest]:
        return [r for r in self.runtime.requests if r.prompt.startswith("The plan of the change")]

    @property
    def asked(self) -> int:
        """How many reviews were asked, counted by the passes that ask the first question."""
        return sum(f"1. {QUESTIONS[0]}" in r.prompt for r in self.passes)

    @property
    def prompt(self) -> str:
        """Every pass of the first review, joined."""
        return "\n".join(r.prompt for r in self.passes[: len(QUESTIONS)])
