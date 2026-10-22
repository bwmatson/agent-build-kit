"""A build commit's body is composed from the proposal's Why and the groups' goals, bounded, and
never read by git as a trailer or comment (spec: commit-messages-say-why)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.commit_body import commit_body
from agent_build_kit.pipeline.stack_runner import GroupStep

WHY = "Reviewers cannot tell what matters."
GOAL = "Done when the body opens with a Start here section."


def change(tmp_path: Path, name: str, why: str | None) -> str:
    """A change directory whose proposal has this Why (none: no proposal file)."""
    directory = tmp_path / "changes" / name
    directory.mkdir(parents=True)
    if why is not None:
        (directory / "proposal.md").write_text(
            f"## Why\n\n{why} More words follow.\n\n## What\n\nx\n"
        )
    return str(directory)


def step(directory: str, goal: str = GOAL, number: int = 1) -> GroupStep:
    return GroupStep(change_dir=directory, number=number, title=f"G{number}", goal=goal)


def test_the_body_holds_the_why_sentence_and_the_goal(tmp_path: Path) -> None:
    steps = [step(change(tmp_path, "feature", WHY))]

    for tests in (True, False):
        body = commit_body(steps, tests=tests)
        assert WHY in body
        assert GOAL in body
        assert "More words follow" not in body, "only the first sentence"
        assert body.index(WHY) < body.index(GOAL)


def test_the_two_bodies_say_what_each_commit_holds(tmp_path: Path) -> None:
    steps = [step(change(tmp_path, "feature", WHY))]

    tests_body = commit_body(steps, tests=True).lower()
    code_body = commit_body(steps, tests=False).lower()

    assert "tests" in tests_body and "first" in tests_body and "fail" in tests_body
    assert "implementation" in tests_body
    assert code_body != tests_body
    assert "fail until" not in code_body


def test_an_unreadable_proposal_gives_the_goal_alone(tmp_path: Path) -> None:
    steps = [step(change(tmp_path, "feature", None))]

    body = commit_body(steps, tests=False)

    assert GOAL in body
    assert WHY not in body


def test_neither_a_why_nor_a_goal_gives_no_body(tmp_path: Path) -> None:
    steps = [step(change(tmp_path, "feature", None), goal="")]

    assert commit_body(steps, tests=True) == ""
    assert commit_body(steps, tests=False) == ""


def test_a_sentence_over_the_limit_is_cut_at_a_word_boundary_with_an_ellipsis(
    tmp_path: Path,
) -> None:
    words = [f"word{n}" for n in range(400)]
    long = " ".join(words) + "."
    steps = [step(change(tmp_path, "feature", long), goal="")]

    body = commit_body(steps, tests=False)

    assert len(body) < len(long)
    assert body.endswith(("…", "..."))
    kept = body.removesuffix("…").removesuffix("...").rstrip().split()[-1]
    assert kept in words, "the last word kept is whole"


def test_a_goal_that_looks_like_a_trailer_is_reworded(tmp_path: Path) -> None:
    steps = [step(change(tmp_path, "feature", WHY), goal="Unit: the marker is built.")]

    body = commit_body(steps, tests=False)

    assert "the marker is built" in body
    assert not any(line.startswith("Unit:") for line in body.splitlines())


def test_a_line_that_looks_like_a_comment_is_reworded(tmp_path: Path) -> None:
    steps = [step(change(tmp_path, "feature", "# Heading is first. Then more."), goal="x\n# y")]

    body = commit_body(steps, tests=True)

    assert "Heading is first" in body
    assert not any(line.lstrip().startswith("#") for line in body.splitlines())


def test_a_unit_of_two_changes_names_each_change_once(tmp_path: Path) -> None:
    first = change(tmp_path, "first", "The first change exists for one reason.")
    second = change(tmp_path, "second", "The second change exists for another.")
    steps = [step(first, "Done when one.", 1), step(first, "Done when two.", 2), step(second)]

    body = commit_body(steps, tests=False)

    assert body.count("The first change exists for one reason.") == 1
    assert body.count("The second change exists for another.") == 1
    assert "Done when one." in body and "Done when two." in body
