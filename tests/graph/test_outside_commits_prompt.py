"""A commit made to a unit's branch by a session that is not the unit's build session is
listed, with its hash, subject, files and session, as authoritative and not to be reverted, in
the unit's next rework, check-fix and review prompts. Nothing is kept for it: the commit's
`Adopted-From` trailer is compared with the build session the unit's thread recorded.

The branch is a real git repository, which the runner's worktree is. The agent is the builder
and reviewer fakes of the graph tests, the builder reporting one session as every run does.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.factories import git, init_repo, unit
from tests.graph.agent_fakes import Reviews
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder, rejecting

BUILD_SESSION = "build-session-1"
FREE_SESSION = "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e91"
OTHER_FREE_SESSION = "9a4c1e77-2d0b-4b58-8e3f-5c7a6d1b0f12"
ADOPTED = ResumeEvent(kind=EventKind.ADOPTED, reason="a chat's commit")
COMMENT = ResumeEvent(
    kind=EventKind.REWORK,
    reason="comment",
    feedback="[comment n1] src/app.py:3 — rename it",
    from_person=True,
    comment_ids=("n1",),
)


class Builder:
    """A builder that is always the one session, recording the prompt of each run by the step
    that sent it."""

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self.by_step: dict[str, list[str]] = {}

    def __call__(
        self,
        prompt: str,
        *,
        cwd: Path,
        on_session: Callable[[str], None] | None = None,
        **more: Any,
    ) -> str:
        if on_session:
            on_session(BUILD_SESSION)
        answer = self.recorder.claude(prompt, cwd=cwd)
        self.by_step.setdefault(self.recorder.events[-1], []).append(prompt)
        return answer


def branch(tmp_path: Path) -> Path:
    """The unit's branch, checked out where the runner's worktree is."""
    repo = init_repo(tmp_path / "tree")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "start")
    git(repo, "checkout", "-q", "-b", "spec/add-marker/1")
    return repo


def land(repo: Path, subject: str, files: dict[str, str], session: str = "") -> str:
    """A commit on the branch, as `abk` makes it: with the unit's trailer and, when it came
    from a chat, the session in `Adopted-From`."""
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    trailers = "Unit: add-marker/1\n" + (f"Adopted-From: {session}\n" if session else "")
    git(repo, "commit", "-q", "-m", f"{subject}\n\n{trailers}")
    return git(repo, "rev-parse", "HEAD").strip()


def drive(tmp_path: Path) -> tuple[Recorder, Builder, dict[str, Any]]:
    recorder = fresh(tmp_path)
    builder = Builder(recorder)
    overrides: dict[str, Any] = dict(
        run=builder,
        run_review=Reviews(recorder),
        run_rework_review=Reviews(recorder),
        worktree=lambda u, base: tmp_path / "tree",
    )
    return recorder, builder, overrides


def mentions(prompt: str, commit: str, subject: str, files: list[str], session: str) -> bool:
    return all(part in prompt for part in (commit[:7], subject, *files, session))


def test_a_free_sessions_commit_is_listed_in_the_next_check_fix_review_and_rework_prompts(
    tmp_path: Path,
) -> None:
    repo = branch(tmp_path)
    recorder, builder, overrides = drive(tmp_path)
    tick(tmp_path, recorder, **overrides)
    assert recorder.store.get(unit().id).state == IN_REVIEW

    # A review comment sends the unit back before anything was committed from outside, and a
    # commit by the unit's own session: neither adds anything.
    own = land(repo, "Tidy the notes", {"src/own.py": "OWN = 1\n"}, BUILD_SESSION)
    tick(tmp_path, recorder, event=COMMENT, **overrides)
    tick(tmp_path, recorder, **overrides)
    [reworked] = builder.by_step["claude:rework"]
    for prompt in (reworked, *recorder.contexts):
        assert "authoritative" not in prompt.lower(), "nothing is said of a commit the agent made"
        assert own[:7] not in prompt

    # A free session commits a source file and a test; its commit is adopted, and the checks fail
    # once, the review asks for a change, and the rework follows.
    outside = land(
        repo,
        "Rename the marker",
        {"src/notes.py": "NOTE = 2\n", "tests/test_notes.py": "def test_note(): ...\n"},
        FREE_SESSION,
    )
    recorder.tier1_results = [(False, "lint: unused import"), (True, "")]
    recorder.verdicts = [rejecting("The note is not tested for the empty case.")]
    reviews_before = len(recorder.contexts)
    tick(tmp_path, recorder, event=ADOPTED, **overrides)
    tick(tmp_path, recorder, **overrides)

    files = ["src/notes.py", "tests/test_notes.py"]
    [fix_prompt] = builder.by_step["claude:fix_checks"]
    [review_context] = recorder.contexts[reviews_before : reviews_before + 1]
    rework_prompt = builder.by_step["claude:rework"][-1]
    for prompt in (fix_prompt, review_context, rework_prompt):
        assert mentions(prompt, outside, "Rename the marker", files, FREE_SESSION), prompt
        lowered = prompt.lower()
        assert "authoritative" in lowered and "revert" in lowered
        assert own[:7] not in prompt, "the unit's own session's commit is not listed"
    assert reworked is not rework_prompt


def test_each_outside_commit_is_listed_with_its_own_session(tmp_path: Path) -> None:
    repo = branch(tmp_path)
    recorder, builder, overrides = drive(tmp_path)
    tick(tmp_path, recorder, **overrides)
    first = land(repo, "First change", {"src/a.py": "A = 1\n"}, FREE_SESSION)
    second = land(repo, "Second change", {"src/b.py": "B = 1\n"}, OTHER_FREE_SESSION)
    recorder.tier1_results = [(False, "lint: nope"), (True, "")]

    tick(tmp_path, recorder, event=ADOPTED, **overrides)
    tick(tmp_path, recorder, **overrides)

    [prompt] = builder.by_step["claude:fix_checks"]
    assert mentions(prompt, first, "First change", ["src/a.py"], FREE_SESSION)
    assert mentions(prompt, second, "Second change", ["src/b.py"], OTHER_FREE_SESSION)
    assert prompt.index("First change") < prompt.index("Second change"), "in branch order"


def test_an_outside_commit_that_changed_a_test_asks_for_keep_adapt_or_retire_only_if_changed(
    tmp_path: Path,
) -> None:
    repo = branch(tmp_path)
    recorder, builder, overrides = drive(tmp_path)
    tick(tmp_path, recorder, **overrides)
    land(repo, "Reword the test", {"tests/test_notes.py": "def test_note(): ...\n"}, FREE_SESSION)
    recorder.tier1_results = [(False, "lint: nope"), (True, "")]

    tick(tmp_path, recorder, event=ADOPTED, **overrides)
    tick(tmp_path, recorder, **overrides)

    [prompt] = builder.by_step["claude:fix_checks"]
    lowered = prompt.lower()
    assert "tests/test_notes.py" in prompt
    assert all(word in lowered for word in ("keep", "adapt", "retire")), "the decision is asked"
    assert "if you change" in lowered, "and only for a test the agent changes"


def test_an_outside_commit_that_changed_no_test_asks_for_no_decision(tmp_path: Path) -> None:
    repo = branch(tmp_path)
    recorder, builder, overrides = drive(tmp_path)
    tick(tmp_path, recorder, **overrides)
    land(repo, "Rename the marker", {"src/notes.py": "NOTE = 2\n"}, FREE_SESSION)
    recorder.tier1_results = [(False, "lint: nope"), (True, "")]

    tick(tmp_path, recorder, event=ADOPTED, **overrides)
    tick(tmp_path, recorder, **overrides)

    [prompt] = builder.by_step["claude:fix_checks"]
    assert "Rename the marker" in prompt
    assert "retire" not in prompt.lower()
