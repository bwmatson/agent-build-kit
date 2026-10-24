"""The tests and implementation commits carry a body saying why: the title, a blank line, the
body, a blank line and the `Unit:` trailer; rework commits are unchanged (spec:
commit-messages-say-why). The branch is real, so the messages are read back from git."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.factories import activate_with, stored_unit
from tests.graph.branch_fakes import TRAILER, UNIT, Groups, OnBranch, built, messages, write_tasks
from tests.graph.test_outside_commits_prompt import branch
from tests.graph_driver import fresh, tick
from tests.runner_fakes import rejecting

WHY = "Reviewers cannot tell what matters."
GOALS: Groups = {1: ("Parse the key", "Done when the key parses.")}


def proposal(tmp_path: Path, text: str) -> None:
    directory = tmp_path / "meta" / "openspec" / "changes" / "add-marker"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "proposal.md").write_text(f"## Why\n\n{text} More words.\n\n## What\n\nx\n")


def test_each_commit_is_title_body_and_trailer(tmp_path: Path) -> None:
    proposal(tmp_path, WHY)
    _, outcome, repo = built(tmp_path, groups={"add-marker": GOALS})

    assert outcome.status == "open"
    made = messages(repo)
    assert len(made) == 2
    for message, title in zip(made, ("test: Parse the key", "feat: Parse the key"), strict=True):
        parts = message.split("\n\n")
        assert parts[0] == title
        assert parts[-1] == TRAILER
        body = "\n\n".join(parts[1:-1])
        assert WHY in body and "Done when the key parses." in body
        assert "More words" not in body
    assert made[0].split("\n\n")[1:] != made[1].split("\n\n")[1:]


def test_an_unstubbed_build_commits_carry_the_why_and_every_groups_goal(tmp_path: Path) -> None:
    proposal(tmp_path, WHY)
    groups: Groups = {
        1: ("Parse the key", "Done when the key parses."),
        2: ("Use the key", "Done when the key is used."),
    }
    _, outcome, repo = built(tmp_path, setting=False, groups={"add-marker": groups})

    assert outcome.status == "open"
    made = messages(repo)
    assert len(made) == 2
    for message, prefix in zip(made, ("test: ", "feat: "), strict=True):
        parts = message.split("\n\n")
        assert parts[0].startswith(prefix)
        assert parts[-1] == TRAILER
        body = "\n\n".join(parts[1:-1])
        assert body.count(WHY) == 1
        assert "Done when the key parses." in body and "Done when the key is used." in body


def test_a_unit_with_no_body_keeps_the_message_of_before(tmp_path: Path) -> None:
    _, outcome, repo = built(tmp_path, groups={"add-marker": {1: ("Parse the key", "")}})

    assert outcome.status == "open"
    assert messages(repo) == [
        f"test: Parse the key\n\n{TRAILER}",
        f"feat: Parse the key\n\n{TRAILER}",
    ]


def test_a_rework_commit_is_unchanged_and_the_pair_has_the_why(tmp_path: Path) -> None:
    activate_with(builders={"stubbed_tdd_commits": True})
    write_tasks(tmp_path, "add-marker", GOALS)
    proposal(tmp_path, WHY)
    repo = branch(tmp_path)
    plain = fresh(tmp_path)
    plain.store.upsert([stored_unit(groups=(1,))])
    recorder = OnBranch(plain.store)
    overrides = recorder.overrides(tmp_path)
    subject = recorder.store.get(UNIT)
    ask = ResumeEvent(
        kind=EventKind.REWORK,
        reason="comment",
        feedback="[comment n1] src/app.py:3 — rename it",
        from_person=True,
        comment_ids=("n1",),
    )

    tick(tmp_path, recorder, subject=subject, **overrides)
    assert recorder.store.get(UNIT).state == IN_REVIEW
    recorder.verdicts = [rejecting("The marker is not tested when empty.")]
    tick(tmp_path, recorder, subject=subject, event=ask, **overrides)
    tick(tmp_path, recorder, subject=subject, **overrides)

    made = messages(repo)
    assert all(WHY in message for message in made[:2])
    fixes = [message for message in made[2:] if message.startswith("fix: ")]
    assert fixes
    assert all(message == f"{message.splitlines()[0]}\n\n{TRAILER}" for message in fixes)
